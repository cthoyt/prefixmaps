"""Classes for managing individual Contexts."""

import re
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Mapping, Optional

import curies

__all__ = [
    "StatusType",
    "PrefixExpansion",
    "Context",
]

CONTEXT = str
PREFIX = str
NAMESPACE = str
PREFIX_EXPANSION_DICT = Mapping[PREFIX, NAMESPACE]
INVERSE_PREFIX_EXPANSION_DICT = Mapping[NAMESPACE, PREFIX]


PREFIX_RE = re.compile(r"^[\w\.]+$")
NAMESPACE_RE = re.compile(r"http[s]?://[\w\.\-\/]+[#/_:]$")


class StatusType(Enum):
    """
    Classification of prefix expansions.

    Note that only canonical mappings are exposed to the users of the library. However,
    it can be useful for prefixmap ETL pipelines to include non-canonical mappings for
    purposes of debugging.
    """

    canonical = "canonical"
    """The canonical prefix expansion for a prefix. The set of all canonical mappings must be bijective."""

    prefix_alias = "prefix_alias"
    """The prefix is an alias for an existing canonical prefix."""

    namespace_alias = "namespace_alias"
    """The prefix is an alias for an existing canonical namespace."""

    multi_alias = "multi_alias"
    """Both the prefix and the namespace are aliases for existing canonical namespaces."""


@dataclass
class PrefixExpansion:
    """
    An individual mapping between a prefix and a namespace.

    A PrefixExpansion corresponds to a SHACL PrefixDeclaration (https://www.w3.org/TR/shacl/#dfn-prefix-declarations)
    """

    context: CONTEXT
    """Each PrefixExpansion is grouped into a context."""

    prefix: PREFIX
    """Corresponds to http://www.w3.org/ns/shacl#prefix"""

    namespace: NAMESPACE
    """Corresponds to http://www.w3.org/ns/shacl#namespace"""

    status: StatusType
    """Indicates whether the expansion is canonical, a prefix alias, a namespace alias, or both."""

    def canonical(self) -> bool:
        """
        True if this is the canonical mapping in both directions.

        Note that canonicality is always relative to a context:

        - ("GEO", "http://purl.obolibrary.org/obo/geo/") is canonical in the OBO Foundry context

        :return: True if the status is canonical
        """
        return self.status == StatusType.canonical

    def validate(self) -> List[str]:
        """
        Validate the prefix expansion.

        - Ensures that prefixes conform to W3C CURIE syntax
        - Ensures that namespaces conform to a restricted subset of W3C URI syntax

        Note that we use a highly restricted syntax in order to filter out pseudo-semantic
        URIs. These include URLs for websites intended for humans that have http parameters
        with `?`s, `=`s, etc.

        These URLs are almost NEVER intended to be used as semantic URIs, i.e as subjects of
        RDF triples. It is almost always bad practice to use them as such.

        In future, if we discover exceptions to this rule, we will add them here.

        :return: list of validation errors
        """
        messages = []
        if not PREFIX_RE.match(self.prefix):
            messages.append(f"prefix {self.prefix} does not match {PREFIX_RE}")
        if not NAMESPACE_RE.match(self.namespace):
            messages.append(
                f"namespace {self.namespace} does not match {NAMESPACE_RE}\
                (prefix: {self.prefix})"
            )
        return messages


@dataclass
class Context:
    """
    A context is a localized collection of prefix expansions.

    A context should be internally consistent:

    - the set of canonical PrefixExpansions should be bijective

    However, there is no guarantee that a context is consistent with other contexts.
    """

    name: CONTEXT
    """A unique stable handle for the context."""

    description: Optional[str] = None
    """A human readable concise description of the context."""

    prefix_expansions: List[PrefixExpansion] = field(default_factory=lambda: [])
    """All prefix expansions within that context. Corresponds to http://www.w3.org/ns/shacl#prefixes"""

    comments: List[str] = None
    """Optional comments on the context."""

    location: Optional[str] = None
    format: Optional[str] = None
    merged_from: Optional[List[str]] = None
    upper: bool = None
    lower: bool = None

    def combine(self, context: "Context"):
        """
        Merge a context into this one.

        If there are conflicts, the current context takes precedence,
        and the merged expansions are marked as non-canonical

        :param context:
        :return:
        """
        for pe in context.prefix_expansions:
            self.add_prefix(pe.prefix, pe.namespace, pe.status)

    def add_prefix(
        self,
        prefix: PREFIX,
        namespace: NAMESPACE,
        status: StatusType = StatusType.canonical,
        preferred: bool = False,
    ):
        """
        Adds a prefix expansion to this context.

        The current context stays canonical. Additional prefixes
        added may be classified as non-canonical.

        If upper or lower is set for this context, the
        prefix will be auto-case normalized,
        UNLESS preferred=True

        :param prefix: prefix to be added
        :param namespace: namespace to be added
        :param status: the status of the prefix being added
        :param preferred:
        :return:
        """
        # TODO: check status
        if not preferred:
            if self.upper:
                prefix = prefix.upper()
                if self.lower:
                    raise ValueError("Cannot set both upper AND lower")
            if self.lower:
                prefix = prefix.lower()
        prefixes = self.prefixes(lower=True)
        namespaces = self.namespaces(lower=True)
        if prefix.lower() in prefixes:
            if namespace.lower() in namespaces:
                return
                # status = StatusType.multi_alias
            else:
                status = StatusType.prefix_alias
        else:
            if namespace.lower() in namespaces:
                status = StatusType.namespace_alias
        self.prefix_expansions.append(
            PrefixExpansion(
                context=self.name,
                prefix=prefix,
                namespace=namespace,
                status=status,
            )
        )

    def filter(self, prefix: PREFIX = None, namespace: NAMESPACE = None):
        """
        Returns namespaces matching query.

        :param prefix:
        :param namespace:
        :return:
        """
        filtered_pes = []
        for pe in self.prefix_expansions:
            if prefix is not None and prefix != pe.prefix:
                continue
            if namespace is not None and namespace != pe.namespace:
                continue
            filtered_pes.append(pe)
        return filtered_pes

    def prefixes(self, lower=False) -> List[str]:
        """
        All unique prefixes in all prefix expansions.

        :param lower: if True, the prefix is normalized to lowercase.
        :return:
        """
        if lower:
            return list({pe.prefix.lower() for pe in self.prefix_expansions})
        else:
            return list({pe.prefix for pe in self.prefix_expansions})

    def namespaces(self, lower=False) -> List[str]:
        """
        All unique namespaces in all prefix expansions

        :param lower: if True, the namespace is normalized to lowercase.
        :return:
        """
        if lower:
            return list({pe.namespace.lower() for pe in self.prefix_expansions})
        else:
            return list({pe.namespace for pe in self.prefix_expansions})

    def as_dict(self) -> PREFIX_EXPANSION_DICT:
        """
        Returns a mapping between canonical prefixes and expansions.

        This only includes canonical expansions. The results can be safely used
        in the header of RDF syntax documents.

        :return: Mappings between prefixes and namespaces
        """
        return {pe.prefix: pe.namespace for pe in self.prefix_expansions if pe.canonical()}

    def as_inverted_dict(self) -> INVERSE_PREFIX_EXPANSION_DICT:
        """
        Returns a mapping between canonical expansions and prefixes.

        :return: Mapping between namespaces and prefixes
        """
        return {pe.namespace: pe.prefix for pe in self.prefix_expansions if pe.canonical()}

    def as_extended_prefix_map(self) -> List[curies.Record]:
        """Return an extended prefix, appropriate for generating a :class:`curies.Converter`.

        An extended prefix map is a collection of dictionaries, each of which has the following
        fields:

        - ``prefix`` - the canonical prefix
        - ``uri_prefix`` - the canonical URI prefix (i.e. namespace)
        - ``prefix_synonyms`` - optional extra prefixes such as capitialization variants. No prefix
          synonyms are allowed to be duplicate across any canonical prefixes or synonyms in other
          records in the extended prefix
        - ``uri_prefix_synonyms`` - optional extra URI prefixes such as variants of Identifiers.org
          URLs, PURLs, etc. No URI prefix synyonms are allowed to be duplicates of either canonical
          or other URI prefix synonyms.

        Extended prefix maps have the benefit over regular prefix maps in that they keep extra
        information. An extended prefix map can be readily collapsed into a normal prefix map
        by getting the ``prefix`` and ``uri_prefix`` fields.
        """
        prefix_map, reverse_prefix_map = {}, {}
        for expansion in self.prefix_expansions:
            if expansion.canonical():
                reverse_prefix_map[expansion.namespace] = expansion.prefix
                prefix_map[expansion.prefix] = expansion.namespace

        uri_prefix_synonyms = defaultdict(set)
        for expansion in self.prefix_expansions:
            if expansion.status == StatusType.prefix_alias:
                uri_prefix_synonyms[expansion.prefix].add(expansion.namespace)

        prefix_synonyms = defaultdict(set)
        for expansion in self.prefix_expansions:
            if (
                expansion.status == StatusType.namespace_alias
                and expansion.namespace in reverse_prefix_map
            ):
                prefix_synonyms[reverse_prefix_map[expansion.namespace]].add(expansion.prefix)
            elif (
                expansion.status == StatusType.namespace_alias
                and expansion.namespace not in reverse_prefix_map
            ):
                warnings.warn(
                    f"Namespace {expansion.namespace} has no canonical prefix", stacklevel=2
                )

        return [
            curies.Record(
                prefix=prefix,
                prefix_synonyms=sorted(prefix_synonyms[prefix]),
                uri_prefix=uri_prefix,
                uri_prefix_synonyms=sorted(uri_prefix_synonyms[prefix]),
            )
            for prefix, uri_prefix in sorted(prefix_map.items())
        ]

    def as_converter(self) -> curies.Converter:
        """Get a converter from this prefix map."""
        extended_prefix_map = self.as_extended_prefix_map()
        return curies.Converter.from_extended_prefix_map(extended_prefix_map)

    def validate(self, canonical_only=True) -> List[str]:
        """
        Validates each prefix expansion in the context.

        :param canonical_only:
        :return:
        """
        messages = []
        for pe in self.prefix_expansions:
            if canonical_only and not pe.canonical():
                continue
            messages += pe.validate()
        # namespaces = self.namespaces(lower=True)
        # prefixes = self.namespaces(lower=True)
        return messages
