"""Reads the Anki package format into nice Python objects.

See https://github.com/ankidroid/Anki-Android/wiki/Database-Structure.

"""
import contextlib
import dataclasses
import functools
import itertools
import json
import pathlib
import sqlite3
import typing
import tempfile
import zipfile

import anki.collection


@dataclasses.dataclass(frozen=True)
class Template:
    name: str
    qfmt: str
    afmt: str
    # format pair for when card is displayed in browser
    bqfmt: str = ""
    bafmt: str = ""
    bfont: str = ""
    bsize: int = 0
    # the deck to add this card to by default
    deck: "Deck" = None
    # template ids were introduced in Anki 2.1.67
    # https://docs.ankiweb.net/importing/packaged-decks.html#note-to-deck-authors 
    id: int = None


@dataclasses.dataclass(frozen=True)
class Field:
    name: str
    font: str = "Liberation Sans"
    size: int = 20
    rtl: bool = False  # right-to-left
    sticky: bool = False  # sticky fields retain the value that was last added when adding new notes
    # field ids were introduced in Anki 2.1.67
    # https://docs.ankiweb.net/importing/packaged-decks.html#note-to-deck-authors 
    id: int = None


@dataclasses.dataclass(frozen=True)
class Model:
    id: int
    name: str
    fields: list[Field]
    css: str
    latex_pre: str
    latex_post: str
    templates: list[Template]
    sort_field: int


@dataclasses.dataclass(frozen=True)
class Note:
    id: int
    guid: int
    model: Model
    field_values: list[str]
    tags: set[str]

    @functools.cached_property
    def fields(self) -> dict[str, str]:
        field_names = (field.name for field in self.model.fields)
        return dict(itertools.zip_longest(field_names, self.field_values, fillvalue=""))


@dataclasses.dataclass(frozen=True)
class Card:
    id: int
    note: Note
    template: int


@dataclasses.dataclass(frozen=True)
class Deck:
    id: int
    name: str
    cards: list[Card]


@dataclasses.dataclass(frozen=True)
class Collection:
    models: list[Model]
    notes: list[Note]
    decks: list[Deck]



@contextlib.contextmanager
def read_collection(path: pathlib.Path):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)

        with zipfile.ZipFile(path) as zf:
            zf.extract("collection.anki2", path=tmpdir)

        yield anki.collection.Collection(tmpdir / "collection.anki2")


@contextlib.contextmanager
def edit_collection(path: pathlib.Path):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)

        with zipfile.ZipFile(path, "r") as zf:
            infos = zf.infolist()
            zf.extractall(path=tmpdir)

        colpath = tmpdir / "collection.anki21"
        if not colpath.exists():
            colpath = tmpdir / "colleciton.anki2"

        col = anki.collection.Collection(colpath)
        yield col
        col.close()

        with zipfile.ZipFile(path, "w") as zf:
            for info in infos:
                if info.is_dir():
                    zf.mkdir(info.filename)
                zf.write(tmpdir / info.filename, info.filename, info.compress_type)


def read_package(path: pathlib.Path) -> Collection:
    with read_collection() as col:
        decks = {}
        for deck in col.decks.all():
            name = deck["name"]
            deck_id = deck["id"]
            decks[deck_id] = Deck(id=deck_id, name=name, cards=[])
    
        models = {}
        for model in col.models.all():
            models[model["id"]] = Model(
                id=model["id"],
                name=model["name"],
                fields=[
                    Field(
                        name=fld["name"],
                        font=fld["font"],
                        size=fld["size"],
                        rtl=fld["rtl"],
                        sticky=fld["sticky"],
                        id=fld["id"],
                    )
                    for fld in model["flds"]
                ],
                css=model["css"],
                latex_pre=model["latexPre"],
                latex_post=model["latexPost"],
                templates=[
                    Template(
                        name=t["name"],
                        qfmt=t["qfmt"],
                        afmt=t["afmt"],
                        bqfmt=t["bqfmt"],
                        bafmt=t["aqfmt"],
                        bfont=t["bfont"],
                        bsize=t["bsize"],
                        deck=decks[t["did"]] if t["did"] else None,
                        id=t["did"],
                    )
                    for t in model["tmpls"]
                ],
                sort_field=model["sortf"],
            )

        notes = {}
        for nid in col.find_notes("*"):
            note = col.get_card(nid)

            model = models[note.mid]
            fields = note.fields
            tags = note.tags
            note = Note(id=int(note.id), guid=note.guid, model=model, field_values=fields, tags=tags)
            notes[note.id] = note

        for cid in col.find_cards("*"):
            card = col.get_card(cid)
            deck = decks[card.did]
            note = notes[card.nid]
            deck.cards.append(Card(id=cid, note=note, template=card.ord))

        return Collection(list(models.values()), list(notes.values()), list(decks.values()))


def yamlify(dataclass, indent: int = 0, bullet: bool = False) -> str:
    lines = []

    for i, field in enumerate(dataclasses.fields(dataclass)):
        if bullet and i == 0:
            prefix = "  " * (indent - 1) + "- "
        else:
            prefix = "  " * indent

        value = getattr(dataclass, field.name)
        if field.type in (int, str, float):
            lines.append(f"{prefix}{field.name}: {value!r}")
        elif field.type is bool:
            lines.append(f"{prefix}{field.name}: {repr(value).lower()}")
        elif typing.get_origin(field.type) in (list, set):
            item_type, = typing.get_args(field.type)
            for elem in value:
                if item_type in (int, str, float):
                    lines.append(f"{prefix}- {elem!r}")
                elif item_type is bool:
                    lines.append(f"{prefix}- {repr(elem).lower()}")
                elif typing.get_origin(item_type) is list:
                    raise NotImplementedError("doubly nested lists not supported")
                else:
                    lines.append(yamlify(elem, indent=indent + 1, bullet=True))
        else:
            lines.append(f"{prefix}{field.name}:")
            lines.append(yamlify(value, indent=indent + 1))
    return "\n".join(lines)