# Potential known issues

These issues were identified with an LLM, but not verified by a human.

Problems found while testing `filter`, `merge` and `slice` against ROS 2 Lyrical (rosbag2 0.33.4), not fixed yet.
Line references are to the rosbag2 source at tag `0.33.4`.

## Data loss or corruption

### Message-compressed bags are copied as compressed bytes (all verbs)

`create_reader()` always uses `SequentialReader`. For bags recorded with `--compression-mode message` it returns the
still-zstd-compressed payload without error, and the output bag (uncompressed metadata) contains undecodable data.

- Fix: use `SequentialCompressionReader` when the bag's `metadata.yaml` has a `compression_format`, like
  `rosbag2_transport::ReaderWriterFactory::make_reader` does.

### File-compressed bags cannot be read (all verbs)

Same cause; fails with `No storage could be initialized. Abort`. Same fix.

### `merge`: a topic with different types in different inputs is written under the first type

`SequentialWriter::create_topic` silently ignores a topic name that already exists (`sequential_writer.cpp:250`),
so messages from the later bag are stored with the first bag's type and cannot be decoded.

- Fix: compare the topic types of all inputs before opening the writer, and fail on a conflict.
  (`ros2 bag convert` skips such topics with a warning.)

### `merge`: differing message definitions of the same type are dropped silently

mcap stores one schema per type (`mcap_storage.cpp`, `MCAPStorage::create_topic`). If the inputs were recorded with
different versions of a message, only the first input's definition is kept.

- Fix: compare the definitions (ignoring comments and whitespace) and warn.

### `merge`: conflicting custom data is dropped silently

For a custom data key present in several inputs, the oldest input's value is kept and the others are dropped.

- Fix: warn on conflicting values.

### `slice`: first or last message can be dropped at the range boundaries

Start and end mode compares `datetime.fromtimestamp(stamp / 1e9)` against the bag start and end computed as
`seconds + nanoseconds / 1e9`. The two float computations round differently: in a test of 200 000 random
timestamps, about 3 % of bags lose their first message and about 3 % their last one, also when no range is given.
The same happens for `-b` / `-e` values exactly on a message timestamp.

- Example timestamps that are dropped: first message at `1791351122000000603`, last at `1791351123000002436`.
- Fix: compare integer nanoseconds; parse `-b` / `-e` with `decimal.Decimal` to convert them exactly.

## Crashes

### `filter`: service event and action topics are not filtered

`StorageFilter(topics=[...])` also returns all service event and action topics unless `services_events` /
`actions` are set. Those topics were not created in the writer, so `filter -i /a` on a bag with service events fails
with `Failed to write on topic '/srv/_service_event'. Call create_topic() before first write.` `-x` also cannot
exclude them.

- Fix: also check the topic of every message read, or set the `services_events` / `actions` filters.

### `filter`: no topic matches

With an empty topic list, `StorageFilter(topics=[])` means no filter, so all messages are read and the first write
fails: `Failed to write on topic '/a'. Call create_topic() before first write.`

- Fix: report that no topics matched before opening the writer.

## Usability

### `-s` defaults to `sqlite3`

mcap input needs `-s mcap`, though Lyrical records mcap by default. The input storage could be detected
automatically (`storage_id=""`) and the output default to the input's format.

### `merge`: output is not in chronological order

Inputs are written one after another. rosbag2 readers sort by timestamp, so playback is correct, but overlapping
inputs give an mcap file with overlapping chunks. `ros2 bag convert` interleaves the inputs by receive timestamp
(`bag_rewrite.cpp`, `get_next`); `heapq.merge` over the readers would do the same.

## Not fixable / harmless

- **Sequence numbers** are not preserved: rosbag2 does not return `sequence_number` when reading. `ros2 bag record`
  always writes 0, so recorded bags lose nothing.
- **`Metadata record with name 'rosbag2' did not contain key 'serialized_metadata'`** when reading mcap bags recorded
  with older rosbag2 versions: the reader falls back to `metadata.yaml`.
