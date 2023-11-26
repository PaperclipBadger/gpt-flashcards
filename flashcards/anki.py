import dataclasses
import functools
import itertools
import json
import pathlib
import sqlite3
import tempfile
import zipfile


@dataclasses.dataclass
class Template:
    name: str
    qfmt: str
    afmt: str


@dataclasses.dataclass(frozen=True)
class Model:
    id: int
    name: str
    field_names: list[str]
    css: str
    latex_pre: str
    latex_post: str
    templates: list[Template]


@dataclasses.dataclass(frozen=True)
class Note:
    id: int
    guid: int
    model: Model
    field_contents: list[str]
    tags: set[str]

    @functools.cached_property
    def fields(self) -> dict[str, str]:
        return dict(itertools.zip_longest(self.model.field_names, self.field_contents, fillvalue=""))


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


def read_package(path: pathlib.Path) -> Collection:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)

        with zipfile.ZipFile(path) as zf:
            zf.extract("collection.anki2", path=tmpdir)

        with sqlite3.connect(tmpdir / "collection.anki2") as conn:
            models_json, = conn.execute("SELECT models FROM col").fetchone()
            decks_json, = conn.execute("SELECT decks FROM col").fetchone()
            notes_rows = conn.execute("SELECT id,guid,mid,mod,flds,tags FROM notes").fetchall()
            cards_rows = conn.execute("SELECT id,nid,did,ord FROM cards").fetchall()

    models = {}
    for mid, model in json.loads(models_json).items():
        models[int(mid)] = Model(
            id=mid,
            name=model["name"],
            field_names=[fld["name"] for fld in model["flds"]],
            css=model["css"],
            latex_pre=model["latexPre"],
            latex_post=model["latexPost"],
            templates=[
                Template(name=t["name"], qfmt=t["qfmt"], afmt=t["afmt"])
                for t in model["tmpls"]
            ],
        )
    
    notes = {}
    for nid, guid, mid, mod, flds, tags in notes_rows:
        model = models[mid]
        fields = flds.split("\x1f")
        tags = set(tags.strip().split())
        note = Note(id=int(nid), guid=guid, model=model, field_contents=fields, tags=tags)
        notes[nid] = note

    decks = {}
    for deck in json.loads(decks_json).values():
        name = deck["name"]
        deck_id = deck["id"]
        decks[deck_id] = Deck(id=deck_id, name=name, cards=[])
    
    for cid, nid, did, ord in cards_rows:
        decks[did].cards.append(Card(id=cid, note=notes[int(nid)], template=int(ord)))
    
    return Collection(list(models.values()), list(notes.values()), list(decks.values()))