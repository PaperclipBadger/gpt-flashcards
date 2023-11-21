import csv
import pathlib
import shutil
import sys

from flashcards.anki import read_package


collection = read_package(sys.argv[1])

output_path = pathlib.Path("deck")
shutil.rmtree(output_path, ignore_errors=True)
output_path.mkdir()

for note in collection.notes:
    keys = list(note.fields.keys())
    keys.append("tags")

    values = list(note.fields.values())
    values.append(", ".join(note.tags))

    row = dict(zip(keys, values))

    path = pathlib.Path(f"deck/{note.model.name}.csv")
    write_header = not path.exists()

    with open(path, "a") as f:
        writer = csv.DictWriter(f, keys)

        if write_header:
            writer.writeheader()

        writer.writerow(row)