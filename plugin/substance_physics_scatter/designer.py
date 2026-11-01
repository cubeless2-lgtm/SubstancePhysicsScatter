"""Designer API adapter. All calls must occur on Designer's UI thread."""
from pathlib import Path
import json
import uuid
import math
import sd
from sd.api.sdapiobject import SDApiError
from .errors import HOST_ERRORS, rollback_or_raise, optional_metadata
from .connections import incoming_sources
from .evaluation import compute_graph
from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
from sd.api.sdresourcebitmap import SDResourceBitmap
from sd.api.sdresource import EmbedMethod
from sd.api.sdproperty import SDPropertyCategory, SDPropertyInheritanceMethod
from sd.api.sdvaluestring import SDValueString
from sd.api.sdvalueint2 import SDValueInt2
from sd.api.sdvalueenum import SDValueEnum
from sd.api.sdbasetypes import float2, int2

KEY = "substance_physics_scatter"
CHANNELS = ("height", "normal", "coverage")

def application():
    return sd.getContext().getSDApplication()


def inspect_terminal_selection(selection, operation_id, owned_directory, forbidden_bitmap_paths):
    """Explicit compute-free inspection; returns plain data, never SDK wrappers."""
    from .terminal_capture import inspect_terminal_selection as inspect
    return inspect(selection, operation_id, owned_directory, forbidden_bitmap_paths)


def capture_terminal(selection, selected_context, operation_id, owned_directory, forbidden_bitmap_paths):
    """Explicit capture operation, separate from selection inspection."""
    from .terminal_capture import capture_terminal as capture
    return capture(selection, selected_context, operation_id, owned_directory, forbidden_bitmap_paths)


def scatter_identity(graph):
    from .fileio import logical_path
    package=graph.getPackage();path=package.getFilePath()
    if not path:raise ValueError("Save the scatter package first")
    return dict(package_path=str(logical_path(path)),package_uid=str(package.getUID()),graph_identifier=graph.getIdentifier(),graph_url=graph.getUrl())


def resolve_scatter(identity):
    matches=[]
    for package in application().getPackageMgr().getUserPackages():
        if str(package.getUID())!=identity['package_uid']:continue
        for graph in package.getChildrenResources(True):
            if isinstance(graph,SDSBSCompGraph) and graph.getIdentifier()==identity['graph_identifier'] and scatter_identity(graph)==identity:matches.append(graph)
    if len(matches)!=1:raise ValueError("Scatter lifetime changed; select it again")
    return matches[0]


def terminal_selections():
    """Current graph declarations only; no image/current value or compute getter."""
    from . import mask_source
    graph=application().getQtForPythonUIMgr().getCurrentGraph()
    if not isinstance(graph,SDSBSCompGraph):raise ValueError("Open the supported source graph first")
    identity=scatter_identity(graph);outputs=graph.getOutputNodes()
    if outputs is None or not 1<=len(outputs)<=5:raise ValueError("Unsupported terminal count")
    result=[];seen=set()
    for node in outputs:
        value=node.getAnnotationPropertyValueFromId('identifier')
        if type(value) is not SDValueString:raise ValueError("Output identifier must be an SDValueString annotation")
        identifier=value.get()
        if not isinstance(identifier,str) or not identifier or identifier in seen:raise ValueError("Output identifiers must be unique")
        seen.add(identifier)
        result.append(mask_source.selection(dict(package_path=identity['package_path'],package_uid=identity['package_uid'],graph_identifier=identity['graph_identifier'],terminal_identifier=identifier)))
    return result


def verify_metadata_current(graph,jobs,current):
    from . import graph_companion as companion
    state=settings(graph) or {};metadata=state.get('current',companion.MISSING)
    if not isinstance(metadata,dict) or metadata.get('job_id')!=current['job_id']:raise ValueError("Designer/current job identity differs")
    companion.read(jobs.directory,current,metadata_ref=metadata.get(companion.KEY,companion.MISSING))


def checked_current(graph,jobs):
    from . import graph_companion as companion
    current=jobs.current;state=settings(graph) or {};metadata=state.get('current',companion.MISSING)
    if current is not None:verify_metadata_current(graph,jobs,current);return current
    if metadata is companion.MISSING:return None
    # Historical File Mask preview recovery only. A graph reference may never be
    # downgraded to metadata-only data when its owned current pointer is missing.
    if not isinstance(metadata,dict) or companion.KEY in metadata:raise ValueError("Owned graph current is missing; restore its result directory")
    companion.read(jobs.directory,metadata,metadata_ref=companion.MISSING)
    return metadata


def require_metadata_unchanged(graph,expected):
    if (settings(graph) or {})!=expected:raise ValueError("Scatter metadata changed during the operation")

def settings(graph):
    raw=optional_metadata(lambda:graph.getMetadataDict().getPropertyValueFromId(KEY),SDApiError.ItemNotFound)
    if raw is None:return None
    value=json.loads(raw.get())
    if not isinstance(value,dict):raise ValueError("Invalid scatter metadata")
    return value

def store(graph, value):
    graph.getMetadataDict().setPropertyValueFromId(KEY, SDValueString.sNew(json.dumps(value)))

def create(parent_graph):
    package = parent_graph.getPackage()
    if not package.getFilePath():
        raise ValueError("Save the SBS package before adding a scatter.")
    identifier = "scatter_" + uuid.uuid4().hex
    graph = SDSBSCompGraph.sNew(package)
    graph.setIdentifier(identifier)
    for i, channel in enumerate(CHANNELS):
        output = graph.newNode("sbs::compositing::output")
        output.setAnnotationPropertyValueFromId("identifier", SDValueString.sNew(channel))
        output.setAnnotationPropertyValueFromId("label", SDValueString.sNew(channel.title()))
        output.setPosition(float2(400, i * 160))
    store(graph, {"node_id": identifier, "version": 1})
    instance = parent_graph.newInstanceNode(graph)
    instance.setPosition(float2(0, 0))
    return graph, instance

def result_directory(graph):
    package = Path(graph.getPackage().getFilePath())
    return package.parent / (package.stem + "_PhysicsScatter") / graph.getIdentifier()

def update(graph, candidate, pending_config=None):
    """Stage all bitmaps before touching stable output nodes; rollback on failure."""
    package = graph.getPackage()
    staged = []
    outputs = {}
    previous = []
    old_properties = []
    old_state = settings(graph)
    def rollback():
        for output, prop, old in previous:
            output.deletePropertyConnections(prop)
            for node, source in old:
                node.newPropertyConnectionFromId(source, output, "inputNodeOutput")
        for owner, prop, value, inheritance in old_properties:
            owner.setPropertyValue(prop, value)
            owner.setPropertyInheritanceMethod(prop, inheritance)
        for _, resource, node in staged:
            graph.deleteNode(node)
            resource.delete()
        if old_state:
            store(graph, old_state)
        compute_graph(graph)
    for output in graph.getOutputNodes():
        outputs[output.getAnnotationPropertyValueFromId("identifier").get()] = output
    try:
        resolution = candidate["request"]["bake"]["resolution"]
        exponent = int(math.log2(resolution))
        if 2 ** exponent != resolution:
            raise ValueError("Designer output resolution must be a power of two")
        size = SDValueInt2.sNew(int2(exponent, exponent))
        def configure(owner, name, value):
            prop = owner.getPropertyFromId(name, SDPropertyCategory.Input)
            # Bitmap/output definitions do not all expose graph-level common properties.
            # The embedded graph owns the mandatory size/precision; imported images keep native data.
            if prop is None:
                return
            old_properties.append((owner, prop, owner.getPropertyValue(prop), owner.getPropertyInheritanceMethod(prop)))
            owner.setPropertyInheritanceMethod(prop, SDPropertyInheritanceMethod.Absolute)
            owner.setPropertyValue(prop, value)
        configure(graph, "$outputsize", size)
        configure(graph, "$format", SDValueEnum.sFromValueId("sbs::compositing::format", "16_bits_per_channel"))
        for i, channel in enumerate(CHANNELS):
            resource = SDResourceBitmap.sNewFromFile(package, candidate["files"][channel], EmbedMethod.Linked)
            resource.setIdentifier("scatter_bitmap_" + uuid.uuid4().hex)
            node = graph.newInstanceNode(resource)
            node.setPosition(float2(0, i * 160))
            staged.append((channel, resource, node))
            format_id = "16_bits_per_channel" if channel == "height" else "8_bits_per_channel"
            # Source and stable output both have explicit settings, independent of parent graph defaults.
            for owner in (node, outputs[channel]):
                configure(owner, "$outputsize", size)
                configure(owner, "$format", SDValueEnum.sFromValueId("sbs::compositing::format", format_id))
        for channel, _, node in staged:
            output = outputs[channel]
            prop = output.getPropertyFromId("inputNodeOutput", SDPropertyCategory.Input)
            previous.append((output, prop, [(source, source_prop.getId()) for source,source_prop in incoming_sources(graph,output.getIdentifier(),"inputNodeOutput")]))
            output.deletePropertyConnections(prop)
            source = node.getProperties(SDPropertyCategory.Output)[0].getId()
            node.newPropertyConnectionFromId(source, output, "inputNodeOutput")
        compute_graph(graph)
        state = dict(old_state or {})
        state["current"] = candidate
        if pending_config is not None:
            state["config"] = pending_config
        store(graph, state)
    except HOST_ERRORS as error:
        rollback_or_raise(error,rollback)
    # Keep old embedded resource nodes for session Undo/recovery; explicit cleanup is a later feature.
    return rollback

def export_outputs(graph, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    compute_graph(graph)
    for output in graph.getOutputNodes():
        name = output.getAnnotationPropertyValueFromId("identifier").get()
        value = output.getPropertyValue(output.getProperties(SDPropertyCategory.Output)[0])
        value.get().save(str(directory / (name + ".png")))
