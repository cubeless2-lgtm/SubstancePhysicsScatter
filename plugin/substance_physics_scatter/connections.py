"""Graph-scoped connection lookup. SDK wrapper handles are never node identities.

Node identifiers are local to the supplied graph, not global identifiers. Callers
must pass the intended graph; this API does not prove an external wrapper's origin.
"""
INPUT=1
OUTPUT=2

def category(prop):
    value=prop.getCategory()
    return value.value if hasattr(value,"value") else value

def incoming_sources(graph,destination_id,input_property_id):
    """Return zero/one canonical (source node, output property) for this graph input.

Both SDK getter orientations are accepted only after exact category/port matching.
No caller-provided connection or node wrapper crosses the graph provenance boundary.
"""
    destination=graph.getNodeFromId(destination_id)
    if destination is None or destination.getIdentifier()!=destination_id:
        raise ValueError("Destination is missing from the stated graph")
    destination_property=destination.getPropertyFromId(input_property_id,_input_category())
    if destination_property is None or category(destination_property)!=INPUT or destination_property.getId()!=input_property_id:
        raise ValueError("Input property is missing or mismatched")
    links=list(destination.getPropertyConnections(destination_property))
    if not links:return []
    if len(links)!=1:raise ValueError("Multiple incoming connections on a single input")
    connection=links[0]
    ends=[(connection.getInputPropertyNode(),connection.getInputProperty()),
          (connection.getOutputPropertyNode(),connection.getOutputProperty())]
    for node,prop in ends:
        if node is None or prop is None:raise ValueError("Missing connection endpoint")
    destinations=[i for i,(node,prop) in enumerate(ends) if node.getIdentifier()==destination_id and prop.getId()==input_property_id and category(prop)==INPUT]
    if len(destinations)!=1:raise ValueError("Missing or ambiguous destination endpoint")
    source,source_property=ends[1-destinations[0]]
    if category(source_property)!=OUTPUT:raise ValueError("Source endpoint is not an Output property")
    source_id=source.getIdentifier()
    canonical=graph.getNodeFromId(source_id)
    if canonical is None or canonical.getIdentifier()!=source_id:raise ValueError("Source is missing from the stated graph")
    output_enum=type(destination_property.getCategory())(OUTPUT)
    output=canonical.getPropertyFromId(source_property.getId(),output_enum)
    if output is None or output.getId()!=source_property.getId() or category(output)!=OUTPUT:
        raise ValueError("Source Output property is missing or mismatched")
    return [(canonical,output)]

def _input_category():
    # The Designer SDK category enum is public and stable (Input=1, Output=2).
    # SDK objects expose it through getPropertyFromId; no private handles are used.
    try:
        from sd.api.sdproperty import SDPropertyCategory
        return SDPropertyCategory.Input
    except ImportError:
        return INPUT
