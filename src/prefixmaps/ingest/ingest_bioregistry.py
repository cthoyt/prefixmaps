"""ETL from bioregistry to prefixmaps."""

import logging

from tqdm import tqdm

from prefixmaps.datamodel.context import NAMESPACE_RE, Context

# Problematic records, look into later
SKIP = {"gro"}


def from_bioregistry_upper(**kwargs) -> Context:
    """
    As :ref:`from_bioregistry`, with default uppercase normalization on

    :param kwargs: pass-through to :ref:`from_bioregistry`
    :return:
    """
    return from_bioregistry(upper=True, **kwargs)


def from_bioregistry(upper=False, canonical_idorg=True, filter_dubious=True) -> Context:
    """
    Creates a Context from the bioregistry.

    This will transform bioregistry entries into semantic prefix expansions.

    Note: in future some of the logic from this can migrate up to the main
    bioregistries repository. For now, we deal with additional corner cases:

    URLs that look like they are not intended to be used as semantic URIs are
    filtered by default. This can be disabled with ``filter_dubious=False``.

    This method also has special handling for the identifiers.org registry
    (aka "miriam"). This is because a number of triplestores have historically
    used URIs of the form "http://identifiers.org/Prefix/LocalId" as the
    subject of their triples. While this is bad practice for "born semantic"
    IDs such as those in OBO, a lot of the bio-semantic web community have
    adopted this practice to provide semantic URIs non-born-semantic databases.
    In order to support this use case, we have an option to preserve these
    original namespaces. This can be disabled with ``canonical_idorg=False``.

    :param upper: if True, normalize prefix to uppercase
                    unless a preferred form is stated
    :param canonical_idorg: use the original/canonical identifiers.org PURLs
    :param filter_dubious: skip namespaces that do not match
                    strict namespace regular expression
    :return:
    """
    import bioregistry

    context = Context("bioregistry", upper=upper)
    prefix_priority = [
        #  "obofoundry.preferred",
        "preferred",
        # "obofoundry",
        "default",
    ]
    priority = [
        "obofoundry",
        "miriam.legacy" if canonical_idorg else "miriam",
        "default",
        "bioportal",
        "ols",
        "n2t",
    ]
    records = bioregistry.get_extended_prefix_map(
        uri_prefix_priority=priority, prefix_priority=prefix_priority
    )
    for record in tqdm(records):
        if record.prefix in SKIP:
            continue
        if filter_dubious and not NAMESPACE_RE.match(record.uri_prefix):
            logging.debug(f"Skipping dubious ns {record.prefix} => {record.uri_prefix}")
            continue
        preferred = record.prefix == bioregistry.get_preferred_prefix(record.prefix)
        context.add_prefix(record.prefix, record.uri_prefix, preferred=preferred)
        # TODO add synonyms, do in later PR since it will increase diff and complexity of review
    return context