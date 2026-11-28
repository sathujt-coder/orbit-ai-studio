"""Deterministic dependency graph and critical path; no provider or execution.

All edges are finish-to-start with zero lag. Timing is an unlimited-resource
lower bound, not a resource allocation, calendar, or committed schedule.
"""
MAX_NODES=150

def analyze(nodes):
    """Accept explicit node IDs, predecessor lists and nullable minutes.

    Reject malformed graphs; never invent durations or a partial critical path.
    Include all zero-float nodes/edges and one deterministic representative path.
    """
    if not isinstance(nodes,list) or not 1<=len(nodes)<=MAX_NODES:
        raise ValueError('Expected 1–150 dependency nodes')
    by_id={}
    for node in nodes:
        tid=node['id'];deps=node['depends_on'];effort=node['effort_minutes']
        if not isinstance(tid,str) or not tid or tid in by_id:
            raise ValueError('Invalid or duplicate dependency node')
        if (not isinstance(deps,list) or any(not isinstance(x,str) for x in deps)
                or len(set(deps))!=len(deps) or tid in deps):
            raise ValueError('Invalid dependency edges')
        if effort is not None and (type(effort) is not int or not 1<=effort<=60000):
            raise ValueError('Invalid dependency duration')
        by_id[tid]=(sorted(deps),effort)
    children={tid:[] for tid in by_id}
    degree={}
    for tid,(deps,_) in by_id.items():
        if not set(deps)<=by_id.keys():raise ValueError('Unknown dependency node')
        degree[tid]=len(deps)
        for dep in deps:children[dep].append(tid)
    for ids in children.values():ids.sort()
    ready=sorted(tid for tid,n in degree.items() if n==0)
    layers=[];order=[]
    while ready:
        layer=ready;layers.append(layer);order.extend(layer);next_layer=[]
        for tid in layer:
            for child in children[tid]:
                degree[child]-=1
                if degree[child]==0:next_layer.append(child)
        ready=sorted(next_layer)
    if len(order)!=len(by_id):raise ValueError('Cyclic dependency graph')
    roots=layers[0];sinks=sorted(tid for tid in by_id if not children[tid])
    edges=[dict(source=dep,target=tid) for tid in sorted(by_id) for dep in by_id[tid][0]]
    missing=[tid for tid in order if by_id[tid][1] is None]
    result=dict(schema='orbit.dependency-graph.v1',node_count=len(by_id),edge_count=len(edges),
        execution_order=order,layers=layers,roots=roots,sinks=sinks,edges=edges,
        unestimated_nodes=missing,timing_ready=not missing,critical_path_minutes=None,
        critical_path=None,critical_nodes=None,critical_edges=None,
        assumptions='finish_to_start_zero_lag_unlimited_resources',
        schedule_committed=False)
    level={tid:i for i,layer in enumerate(layers) for tid in layer}
    rows={tid:dict(id=tid,layer=level[tid],depends_on=by_id[tid][0],
        successors=children[tid],effort_minutes=by_id[tid][1],
        earliest_start_minutes=None,earliest_finish_minutes=None,
        latest_start_minutes=None,latest_finish_minutes=None,total_float_minutes=None,
        critical=None) for tid in order}
    result['nodes']=list(rows.values())
    if missing:return result
    # Forward pass. Deterministic tie selection does not enumerate exponential paths.
    es={};ef={};parent={}
    for tid in order:
        deps,duration=by_id[tid]
        es[tid]=max((ef[dep] for dep in deps),default=0)
        ef[tid]=es[tid]+duration
        parent[tid]=min((dep for dep in deps if ef[dep]==es[tid]),default=None)
    bound=max(ef.values())
    # Backward pass with a shared virtual finish for disconnected components.
    ls={};lf={}
    for tid in reversed(order):
        lf[tid]=min((ls[child] for child in children[tid]),default=bound)
        ls[tid]=lf[tid]-by_id[tid][1]
        slack=ls[tid]-es[tid]
        rows[tid].update(earliest_start_minutes=es[tid],earliest_finish_minutes=ef[tid],
            latest_start_minutes=ls[tid],latest_finish_minutes=lf[tid],
            total_float_minutes=slack,critical=slack==0)
    critical={tid for tid in order if rows[tid]['critical']}
    end=min(tid for tid in sinks if ef[tid]==bound)
    path=[]
    while end is not None:
        path.append(end);end=parent[end]
    result.update(critical_path_minutes=bound,critical_path=list(reversed(path)),
        critical_nodes=[tid for tid in order if tid in critical],
        critical_edges=[edge for edge in edges if edge['source'] in critical and
            edge['target'] in critical and ef[edge['source']]==es[edge['target']]])
    return result
