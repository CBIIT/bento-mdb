"""Common functions shared by changelog generation scripts."""

from __future__ import annotations

import configparser
import logging
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Generator

from bento_meta.objects import Edge, Property, Tag
from minicypher.clauses import Clause, Match
from minicypher.entities import G, N, P, R, T, _condition, _return
from minicypher.functions import Func

if TYPE_CHECKING:
    from bento_meta.entity import Entity

logger = logging.getLogger(__name__)


def get_initial_changeset_id(config_file_path: str | Path) -> int:
    """Get initial changeset id from changelog config file."""
    config = configparser.ConfigParser()
    config.read(config_file_path)
    try:
        return config.getint(section="changelog", option="changeset_id")
    except (configparser.NoSectionError, configparser.NoOptionError):
        logging.exception("Reading changeset ID failed")
        raise


def changeset_id_generator(config_file_path: str | Path) -> Generator[int, None, None]:
    """Generate sequential changeset IDs by reading the latest ID from a config file."""
    i = get_initial_changeset_id(config_file_path)
    while True:
        yield i
        i += 1


def update_config_changeset_id(
    config_file_path: str | Path,
    new_changeset_id: int,
) -> None:
    """Update changelog config file with new changeset id."""
    config = configparser.ConfigParser()
    config.read(config_file_path)
    config.set(section="changelog", option="changeset_id", value=str(new_changeset_id))
    with Path(config_file_path).open(mode="w", encoding="UTF-8") as config_file:
        config.write(fp=config_file)


def escape_quotes_in_attr(entity: Entity) -> None:
    """
    Escapes quotes in entity attributes.

    Quotes in string attributes may or may not already be escaped, so this function
    unescapes all previously escaped ' and " characters and replaces them with
    """
    for key, val in vars(entity).items():
        if (
            val
            and val is not None
            and key != "pvt"
            and isinstance(
                val,
                str,
            )
        ):
            # First unescape any previously escaped quotes
            unescape_val = val.replace(r"\'", "'").replace(r"\"", '"')

            # Escape all quotes
            escape_val = unescape_val.replace("'", r"\'").replace('"', r"\"")

            # Update the modified value back to the attribute
            setattr(entity, key, escape_val)


def reset_pg_ent_counter() -> None:
    """Reset property graph entity variable counters to 0."""
    N._reset_counter()
    R._reset_counter()


def generate_match_clause(entity: Entity, ent_c: N) -> Match:
    """Generate Match clause for entity."""
    if isinstance(entity, Edge):
        return match_edge(edge=entity, ent_c=ent_c)
    if isinstance(entity, Property):  # remove '_parent_handle' from ent_c property
        ent_c.props.pop("_parent_handle", None)
        return match_prop(prop=entity, ent_c=ent_c)
    if isinstance(entity, Tag):
        return match_tag(tag=entity, ent_c=ent_c)
    return Match(ent_c)


def match_edge(edge: Edge, ent_c: N) -> Match:
    """Add MATCH statement for edge."""
    src_c = N(label="node", props=edge.src.get_attr_dict())
    dst_c = N(label="node", props=edge.dst.get_attr_dict())
    src_trip = T(ent_c, R(Type="has_src"), src_c)
    dst_trip = T(ent_c, R(Type="has_dst"), dst_c)
    path = G(src_trip, dst_trip)
    return Match(path)


def match_prop(prop: Property, ent_c: N) -> Match:
    """Add MATCH statement for property."""
    if not prop._parent_handle:
        msg = f"Property missing parent handle {prop.get_attr_dict()}"
        raise AttributeError(msg)
    par_c = N(props={"handle": prop._parent_handle})
    prop_trip = T(par_c, R(Type="has_property"), ent_c)
    return Match(prop_trip)


def match_tag(tag: Tag, ent_c: N) -> Match:
    """Add MATCH statement for tag."""
    if not tag._parent:
        msg = f"Tag missing parent {tag.get_attr_dict()}"
        raise AttributeError(msg)
    parent = tag._parent
    par_c = N(label=parent.get_label(), props=parent.get_attr_dict())
    par_c.props.pop("_parent_handle", None)
    # temp workaround for long matches
    par_match_clause = generate_match_clause(entity=parent, ent_c=par_c)
    par_match_str = str(par_match_clause)[6:]
    tag_trip = T(par_c.plain_var(), R(Type="has_tag"), ent_c)
    return Match(par_match_str, tag_trip)


class Case(Clause):
    """Create a CASE clause with the arguments."""

    template = Template("CASE $slot1")

    def __init__(self, *args):
        super().__init__(*args)


class Delete(Clause):
    """Create a DELETE clause with the arguments."""

    template = Template("DELETE $slot1")

    def __init__(self, *args):
        super().__init__(*args)


class DetachDelete(Clause):
    """Create a DETACH DELETE clause with the arguments."""

    template = Template("DETACH DELETE $slot1")

    def __init__(self, *args):
        super().__init__(*args)


class ForEach(Clause):
    """Create an FOREACH clause with the arguments."""

    template = Template("FOREACH $slot1")

    def __init__(self, *args):
        super().__init__(*args)


class Statement:
    """Create a Neo4j statement comprised of clauses (and strings) in order."""

    def __init__(self, *args, terminate=False, use_params=False):
        self.clauses = args
        self.terminate = terminate
        self.use_params = use_params
        self._params = None

    def __str__(self):
        stash = P.parameterize
        if self.use_params:
            P.parameterize = True
        else:
            P.parameterize = False
        ret = " ".join([str(x) for x in self.clauses])
        if self.terminate:
            ret = ret + ";"
        P.parameterize = stash
        return ret

    @property
    def params(self):
        if self._params is None:
            self._params = {}
            for c in self.clauses:
                for ent in c.args:
                    if isinstance(ent, (N, R)):
                        for p in ent.props.values():
                            self._params[p.var] = p.value
                    else:
                        if "nodes" in vars(type(ent)):
                            for n in ent.nodes():
                                for p in n.props.values():
                                    self._params[p.var] = p.value
                        if "edges" in vars(type(ent)):
                            for e in ent.edges():
                                for p in e.props.values():
                                    self._params[p.var] = p.value
        return self._params


class With(Clause):
    """Create a WITH clause with the arguments."""

    template = Template("WITH $slot1")

    def __init__(self, *args):
        super().__init__(*args)

    @staticmethod
    def context(arg: object) -> str:
        return _return(arg)


class When(Clause):
    """Create a WHEN clause with the arguments."""

    template = Template("WHEN $slot1")
    joiner = " {} "

    @staticmethod
    def context(arg):
        return _condition(arg)

    def __init__(self, *args, op="AND"):
        super().__init__(*args, op=op)
        self.op = op

    def __str__(self):
        values = []
        for c in [self.context(x) for x in self.args]:
            if isinstance(c, str):
                values.append(c)
            elif isinstance(c, Func):
                values.append(str(c))
            elif isinstance(c, list):
                values.extend([str(x) for x in c])
            else:
                values.append(str(c))
        return self.template.substitute(slot1=self.joiner.format(self.op).join(values))
