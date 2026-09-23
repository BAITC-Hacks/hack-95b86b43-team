import csv


def read_table(directory, name):
    with (directory / f"{name}.csv").open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def write_table(directory, name, fields, rows, encoding="utf-8"):
    with (directory / f"{name}.csv").open("w", encoding=encoding, newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def change(directory, table, field, value, index=0):
    fields, rows = read_table(directory, table)
    rows[index][field] = value
    write_table(directory, table, fields, rows)
