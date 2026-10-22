# Copyright 2021 Tier IV, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Modified 2026 by Eelis Peltola: keep message definitions, QoS profiles, custom data and send timestamps of
# the input bags; verify written message counts.

from collections import Counter
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from rosbag2_py import *
from rclpy.time import Time
from rosbag2_py_wrapper import SequentialWriterWrapper


def create_reader(bag_dir: str, storage_type: str) -> SequentialReader:
    storage_options = get_storage_options(bag_dir, storage_type)
    converter_options = get_default_converter_options()

    reader = SequentialReader()
    reader.open(storage_options, converter_options)
    return reader


def _action_name(topic_name: str) -> Optional[str]:
    if "/_action/" not in topic_name:
        return None
    return topic_name.split("/_action/", 1)[0]


def _action_types(topics: Iterable[TopicMetadata]) -> Dict[str, str]:
    # e.g. '/fibonacci/_action/feedback' with 'example_interfaces/action/Fibonacci_FeedbackMessage'
    #   -> {'/fibonacci': 'example_interfaces/action/Fibonacci'}
    action_types = {}
    for topic in topics:
        action_name = _action_name(topic.name)
        if action_name is not None and "/action/" in topic.type:
            package, interface = topic.type.split("/action/", 1)
            action_types.setdefault(action_name, "{}/action/{}".format(package, interface.split("_", 1)[0]))
    return action_types


def _definition_keys(topic: TopicMetadata, action_types: Dict[str, str]) -> List[str]:
    # NOTE: mcap keys message definitions by topic type, while sqlite3 keys them by the type rosbag2 resolved the
    # definition for: the service type for service events, and the action type for all topics of an action.
    keys = []
    action_name = _action_name(topic.name)
    if action_name in action_types:
        keys.append(action_types[action_name])
    keys.append(topic.type)
    if topic.type.endswith("_Event"):
        keys.append(topic.type[:-len("_Event")])
    return keys


class _BagDefinitions:
    ''' Message definitions stored in a bag, looked up by topic. '''
    def __init__(self, reader: SequentialReader):
        self._definitions = {
            definition.topic_type: definition for definition in reader.get_all_message_definitions()
            if definition.encoding and definition.encoding != "unknown" and definition.encoded_message_definition}
        self._action_types = _action_types(reader.get_all_topics_and_types())

    def find(self, topic: TopicMetadata) -> Optional[MessageDefinition]:
        for key in _definition_keys(topic, self._action_types):
            if key in self._definitions:
                return self._definitions[key]
        return None


def collect_topics(
        readers: Sequence[SequentialReader],
        topic_names: Optional[Iterable[str]] = None) -> List[Tuple[TopicMetadata, Optional[MessageDefinition]]]:
    ''' Combine the topics of the input bags, with the message definitions stored in the bags. '''
    topic_names = None if topic_names is None else set(topic_names)
    topics: Dict[str, Tuple[TopicMetadata, Optional[MessageDefinition]]] = {}
    for reader in readers:
        bag_definitions = _BagDefinitions(reader)
        for topic in reader.get_all_topics_and_types():
            if topic_names is not None and topic.name not in topic_names:
                continue
            if topic.name not in topics:
                topics[topic.name] = (topic, bag_definitions.find(topic))
                continue
            combined, definition = topics[topic.name]
            # NOTE: Like `ros2 bag convert`, keep the QoS profiles offered in all inputs.
            combined.offered_qos_profiles = list(combined.offered_qos_profiles) + list(topic.offered_qos_profiles)
            if definition is None:
                topics[topic.name] = (combined, bag_definitions.find(topic))
    return list(topics.values())


def collect_custom_data(readers: Sequence[SequentialReader]) -> Dict[str, str]:
    ''' Combine the custom data of the input bags. For keys in several bags, the first bag's value is kept. '''
    custom_data: Dict[str, str] = {}
    for reader in readers:
        for key, value in reader.get_metadata().custom_data.items():
            custom_data.setdefault(key, value)
    return custom_data


class BagWriter:
    ''' Writes a bag and verifies on close that every message was stored. '''
    def __init__(self, uri: str, storage_type: str, custom_data: Optional[Dict[str, str]] = None):
        self.uri = uri
        self._counts: Counter = Counter()
        storage_options = get_storage_options(uri, storage_type)
        storage_options.custom_data = custom_data or {}
        self._writer = SequentialWriterWrapper()
        self._writer.open(storage_options, get_default_converter_options())

    def create_topics(self, topics: Iterable[Tuple[TopicMetadata, Optional[MessageDefinition]]]) -> None:
        # NOTE: Pass the input bag's message definitions through, so that types which are not installed locally
        # do not end up with an empty schema in the output bag.
        for topic, definition in topics:
            if definition is not None:
                self._writer.create_topic(topic, definition)
            else:
                # Fall back to the message definition of the locally installed type, if any
                self._writer.create_topic(topic)

    def write(self, topic_name: str, message: bytes, recv_timestamp: int, send_timestamp: int) -> None:
        self._writer.write(topic_name, message, recv_timestamp, send_timestamp)
        self._counts[topic_name] += 1

    def split_bagfile(self) -> None:
        self._writer.split_bagfile()

    def close(self) -> None:
        self._writer.close()
        verify_message_counts(self.uri, self._counts)


def verify_message_counts(uri: str, expected_counts: Dict[str, int]) -> None:
    # NOTE: The writer does not raise when the storage fails to write a message, it only counts it as lost.
    metadata = MetadataIo().read_metadata(uri)
    counts = {topic.topic_metadata.name: topic.message_count for topic in metadata.topics_with_message_count}
    mismatches = [
        "{}: wrote {}, stored {}".format(topic, count, counts.get(topic))
        for topic, count in sorted(expected_counts.items()) if counts.get(topic) != count]
    if mismatches:
        raise RuntimeError("Messages were lost while writing '{}':\n  {}".format(uri, "\n  ".join(mismatches)))


def get_default_converter_options() -> ConverterOptions:
    return ConverterOptions(
        input_serialization_format="cdr",
        output_serialization_format="cdr",
    )


def get_storage_options(uri: str, storage_type: str) -> StorageOptions:
    return StorageOptions(
        uri=uri,
        storage_id=storage_type,
    )


def get_starting_time(uri: str, storage_type: str) -> datetime:
    info = Info().read_metadata(uri, storage_type)
    starting_time: datetime | Time = info.starting_time
    if isinstance(starting_time, datetime):
        return starting_time
    return rcl_py_time_to_datetime(starting_time)

def get_ending_time(uri: str, storage_type: str) -> datetime:
    info = Info().read_metadata(uri, storage_type)
    ending_time: datetime | Time = info.starting_time + info.duration
    if isinstance(ending_time, datetime):
        return ending_time
    return rcl_py_time_to_datetime(ending_time)


def rcl_py_time_to_datetime(ros_time: Time) -> datetime:
    second, nanosecond = ros_time.seconds_nanoseconds()
    timestamp = second + (nanosecond / 10**9)
    return datetime.fromtimestamp(timestamp)
