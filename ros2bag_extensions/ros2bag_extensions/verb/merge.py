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
# Modified 2026 by Eelis Peltola: keep message definitions, QoS profiles, custom data and send timestamps;
# verify written messages.

import os
from typing import List

from ros2bag.api import check_path_exists
from ros2bag.verb import VerbExtension

from . import (BagWriter, collect_custom_data, collect_topics, create_reader,
               get_starting_time)


class MergeVerb(VerbExtension):
    ''' Combine multiple bag files '''
    def _bag2merge(self, input_bags: List[str], output_bag_dir: str, storage_type: str) -> None:
        # NOTE: To make SequentialWriter work properly, read starting_time in order of oldest to newest.
        input_bags = sorted(input_bags, key=lambda bag: get_starting_time(bag, storage_type))
        readers = [create_reader(input_bag, storage_type) for input_bag in input_bags]

        # Open writer
        writer = BagWriter(output_bag_dir, storage_type, collect_custom_data(readers))

        # Create topics
        # NOTE: Create the topics of all inputs before writing, so that the QoS profiles of all inputs are combined.
        writer.create_topics(collect_topics(readers))

        # Write
        # NOTE: In the case of SQLite3 storage, it is sorted by ORDERED BY timestamp when reading, so sorting is not necessary when writing.
        for reader in readers:
            while reader.has_next():
                topic_name, msg, stamp, send_stamp = reader.read_next_ext()
                writer.write(topic_name, msg, stamp, send_stamp)
        writer.close()


    def add_arguments(self, parser, cli_name):
        parser.add_argument(
            "bag_directory", type=check_path_exists, nargs="+", help="Bag to filter")
        parser.add_argument(
            "-o", "--output", required=True, help="Output directory")
        parser.add_argument(
            "-s", "--storage", required=False, default="sqlite3", help="storage identifier to be used, defaults to 'sqlite3'")


    def main(self, *, args):
        if os.path.isdir(args.output):
            raise FileExistsError("Output folder '{}' already exists.".format(args.output))

        self._bag2merge(args.bag_directory, args.output, args.storage)
