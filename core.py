import bpy
import math
import random
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras import view3d_utils


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

PROFILE_COLLECTION_NAME = "Hair Profiles"
SURFACE_OFFSET = 0.001
TARGET_PROFILE_RADIUS = 0.01
HAIR_MECHA_PREFIX = "HairMecha"
HAIR_GROWTH_PREFIX = "HairGrowth"

DEFAULT_GUIDE_LENGTH = 0.12
DEFAULT_GUIDE_LIFT = 0.35
DEFAULT_GUIDE_ANGLE = 0.0
DEFAULT_GUIDE_CURVE = 0.35
DEFAULT_GUIDE_TIP_TAPER = 0.15
DEFAULT_ROOT_EMBED_DEPTH = 0.01
DEFAULT_GROWTH_COUNT = 250
DEFAULT_GROWTH_LENGTH_VARIATION = 0.25
DEFAULT_GROWTH_ANGLE_VARIATION = 18.0
DEFAULT_GROWTH_SEED = 1
DEFAULT_GROWTH_MIN_SPACING = 0.010
DEFAULT_GROWTH_SPACING_ATTEMPTS = 10
DEFAULT_GROWTH_MIRROR = True
DEFAULT_GROWTH_FILL_MODE = True

DEFAULT_GROWTH_WEIGHT_THRESHOLD = 0.05
DEFAULT_GROWTH_WEIGHT_AFFECTS_LENGTH = True
DEFAULT_GROWTH_LENGTH_WEIGHT_MIN = 0.4
DEFAULT_GROWTH_WEIGHT_AFFECTS_THICKNESS = True
DEFAULT_GROWTH_THICKNESS_WEIGHT_MIN = 0.3
DEFAULT_GROWTH_TIP_TAPER = 0.35

DEFAULT_CLOSE_TIPS = True

DEFAULT_COMB_RADIUS = 60.0
DEFAULT_COMB_STRENGTH = 0.6
DEFAULT_COMB_PIN_ROOT = True
COMB_UNDO_STEPS = 50


# ---------------------------------------------------------------------------
# Perfil de seção transversal
# ---------------------------------------------------------------------------


def get_profile_collection():
    coll = bpy.data.collections.get(PROFILE_COLLECTION_NAME)
    if coll is None:
        coll = bpy.data.collections.new(PROFILE_COLLECTION_NAME)
        bpy.context.scene.collection.children.link(coll)
        layer_coll = bpy.context.view_layer.layer_collection.children.get(coll.name)
        if layer_coll:
            layer_coll.exclude = True
    return coll


def _new_curve_object(name, points_xy, cyclic, smooth=False):
    curve_data = bpy.data.curves.new(name, type='CURVE')
    curve_data.dimensions = '2D'
    spline_type = 'NURBS' if smooth else 'POLY'
    spline = curve_data.splines.new(spline_type)
    spline.points.add(len(points_xy) - 1)
    for i, (x, y) in enumerate(points_xy):
        spline.points[i].co = (x, y, 0.0, 1.0)
    spline.use_cyclic_u = cyclic

    if smooth and spline_type == 'NURBS':
        spline.order_u = min(4, len(points_xy))
        spline.use_endpoint_u = not cyclic
        curve_data.resolution_u = 12

    obj = bpy.data.objects.new(name, curve_data)
    get_profile_collection().objects.link(obj)
    obj.hide_render = True
    return obj


def make_round_profile(radius=0.01, segments=8, smooth=True):
    pts = []
    for i in range(segments):
        a = (2 * math.pi * i) / segments
        pts.append((radius * math.cos(a), radius * math.sin(a)))
    suffix = "smooth" if smooth else "rigid"
    return _new_curve_object(f"HairProfile_Round_{segments}_{suffix}", pts, cyclic=True, smooth=smooth)


def make_flat_profile(width=0.02, depth=0.0, segments=7, smooth=True):
    segments = max(2, segments)
    half = width * 0.5

    pts = []
    for i in range(segments):
        t = i / (segments - 1)
        x = -half + t * width
        norm = (x / half) if half > 1e-9 else 0.0
        y = (depth * half) * (1.0 - norm ** 2)
        pts.append((x, y))

    suffix = "smooth" if smooth else "rigid"
    name = f"HairProfile_Flat_{round(depth * 10000)}_{segments}_{suffix}"
    return _new_curve_object(name, pts, cyclic=False, smooth=smooth)


def make_square_profile(size=0.015):
    half = size * 0.5
    pts = [(-half, -half), (half, -half), (half, half), (-half, half)]
    return _new_curve_object("HairProfile_Square", pts, cyclic=True)


def make_star_profile(outer=0.015, inner=0.006, points=5, smooth=True):
    pts = []
    total = points * 2
    for i in range(total):
        radius = outer if i % 2 == 0 else inner
        a = (2 * math.pi * i) / total
        pts.append((radius * math.cos(a), radius * math.sin(a)))
    suffix = "smooth" if smooth else "rigid"
    return _new_curve_object(f"HairProfile_Star_{suffix}", pts, cyclic=True, smooth=smooth)


def _add_circle_spline_to_curve(curve_data, cx, cy, radius, segments, smooth):
    pts = []
    for i in range(segments):
        a = (2 * math.pi * i) / segments
        pts.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))

    spline_type = 'NURBS' if smooth else 'POLY'
    spline = curve_data.splines.new(spline_type)
    spline.points.add(len(pts) - 1)
    for i, (x, y) in enumerate(pts):
        spline.points[i].co = (x, y, 0.0, 1.0)
    spline.use_cyclic_u = True

    if smooth and spline_type == 'NURBS':
        spline.order_u = min(4, len(pts))
        spline.use_endpoint_u = False


def make_clump_profile(strand_count=5, cluster_spread=0.006, strand_radius=0.0015, smooth=True):
    suffix = "smooth" if smooth else "rigid"
    name = (
        f"HairProfile_Clump_{strand_count}_"
        f"{round(cluster_spread * 10000)}_{round(strand_radius * 10000)}_{suffix}"
    )

    curve_data = bpy.data.curves.new(name, type='CURVE')
    curve_data.dimensions = '2D'
    if smooth:
        curve_data.resolution_u = 12

    rng = random.Random(1234)
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    segments = 8

    for i in range(strand_count):
        r = cluster_spread * math.sqrt((i + 0.5) / strand_count)
        theta = i * golden_angle
        cx = r * math.cos(theta)
        cy = r * math.sin(theta)
        this_radius = strand_radius * rng.uniform(0.7, 1.3)
        _add_circle_spline_to_curve(curve_data, cx, cy, this_radius, segments, smooth)

    obj = bpy.data.objects.new(name, curve_data)
    get_profile_collection().objects.link(obj)
    obj.hide_render = True
    return obj


PROFILE_BUILDERS = {
    'ROUND': make_round_profile,
    'FLAT': make_flat_profile,
    'SQUARE': make_square_profile,
    'STAR': make_star_profile,
}


def get_or_create_profile(kind, segments=8, smooth=True, clump_count=5,
                          clump_spread=0.006, clump_strand_radius=0.0015,
                          flat_depth=0.0, flat_segments=7):
    if kind == 'ROUND':
        suffix = "smooth" if smooth else "rigid"
        name = f"HairProfile_Round_{segments}_{suffix}"
        existing = bpy.data.objects.get(name)
        if existing:
            return existing
        return make_round_profile(segments=segments, smooth=smooth)

    if kind == 'STAR':
        suffix = "smooth" if smooth else "rigid"
        name = f"HairProfile_Star_{suffix}"
        existing = bpy.data.objects.get(name)
        if existing:
            return existing
        return make_star_profile(smooth=smooth)

    if kind == 'FLAT':
        suffix = "smooth" if smooth else "rigid"
        name = f"HairProfile_Flat_{round(flat_depth * 10000)}_{flat_segments}_{suffix}"
        existing = bpy.data.objects.get(name)
        if existing:
            return existing
        return make_flat_profile(depth=flat_depth, segments=flat_segments, smooth=smooth)

    if kind == 'CLUMP':
        suffix = "smooth" if smooth else "rigid"
        name = (
            f"HairProfile_Clump_{clump_count}_"
            f"{round(clump_spread * 10000)}_{round(clump_strand_radius * 10000)}_{suffix}"
        )
        existing = bpy.data.objects.get(name)
        if existing:
            return existing
        return make_clump_profile(clump_count, clump_spread, clump_strand_radius, smooth)

    existing = bpy.data.objects.get("HairProfile_Square")
    if existing:
        return existing
    return PROFILE_BUILDERS[kind]()


def _profile_local_max_extent(obj):
    max_extent = 0.0
    if obj.data and hasattr(obj.data, "splines"):
        for spline in obj.data.splines:
            for p in spline.points:
                d = math.sqrt(p.co.x ** 2 + p.co.y ** 2 + p.co.z ** 2)
                max_extent = max(max_extent, d)
            for p in getattr(spline, "bezier_points", []):
                d = math.sqrt(p.co.x ** 2 + p.co.y ** 2 + p.co.z ** 2)
                max_extent = max(max_extent, d)
    return max_extent


def get_profile_base_scale(obj):
    return obj.get("hair_profile_base_scale", 1.0)


def apply_profile_scale(obj, thickness_scale):
    base = get_profile_base_scale(obj)
    s = base * thickness_scale
    obj.scale = (s, s, s)


def normalize_custom_profile_scale(obj, thickness_scale, force=False):
    if not force and obj.get("hair_profile_normalized"):
        return

    max_extent = _profile_local_max_extent(obj)
    if max_extent <= 0.0:
        return

    base_scale = TARGET_PROFILE_RADIUS / max_extent
    obj["hair_profile_base_scale"] = base_scale
    obj["hair_profile_normalized"] = True
    apply_profile_scale(obj, thickness_scale)


# ---------------------------------------------------------------------------
# Superfície / raycast
# ---------------------------------------------------------------------------


def _bvh_from_evaluated_object(obj_eval):
    try:
        temp_mesh = obj_eval.to_mesh()
    except RuntimeError:
        return None

    if temp_mesh is None:
        return None

    temp_mesh.calc_loop_triangles()
    if not temp_mesh.loop_triangles:
        obj_eval.to_mesh_clear()
        return None

    vertices = [v.co.copy() for v in temp_mesh.vertices]
    triangles = [tri.vertices for tri in temp_mesh.loop_triangles]
    bvh = BVHTree.FromPolygons(vertices, triangles)

    obj_eval.to_mesh_clear()
    return bvh


def _raycast_object(obj_eval, origin_local, dir_local):
    if obj_eval.type == 'MESH':
        try:
            return obj_eval.ray_cast(origin_local, dir_local)
        except RuntimeError:
            pass

    bvh = _bvh_from_evaluated_object(obj_eval)
    if bvh is None:
        return (False, None, None, -1)

    location, normal, index, distance = bvh.ray_cast(origin_local, dir_local)
    if location is None:
        return (False, None, None, -1)
    return (True, location, normal, index)


def raycast_targets(context, coord, targets):
    region = context.region
    rv3d = context.region_data
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    ray_dir = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

    depsgraph = context.evaluated_depsgraph_get()
    best_hit = None
    best_normal = None
    best_dist = None

    for target_obj in targets:
        if target_obj is None:
            continue
        obj_eval = target_obj.evaluated_get(depsgraph)

        matrix = target_obj.matrix_world
        matrix_inv = matrix.inverted()
        origin_local = matrix_inv @ ray_origin
        dir_local = (matrix_inv.to_3x3() @ ray_dir).normalized()

        success, loc, normal, face_index = _raycast_object(obj_eval, origin_local, dir_local)
        if not success:
            continue

        world_loc = matrix @ loc
        dist = (world_loc - ray_origin).length
        if best_dist is None or dist < best_dist:
            best_dist = dist
            world_normal = (matrix.to_3x3() @ normal).normalized()
            best_hit = world_loc + world_normal * SURFACE_OFFSET
            best_normal = world_normal

    if best_hit is None:
        return None
    return best_hit, best_normal, best_dist


def _closest_point_on_object(obj_eval, point_local):
    if obj_eval.type == 'MESH':
        try:
            success, location, normal, index = obj_eval.closest_point_on_mesh(point_local)
            if success:
                return (True, location, normal, index)
        except RuntimeError:
            pass

    bvh = _bvh_from_evaluated_object(obj_eval)
    if bvh is None:
        return (False, None, None, -1)

    location, normal, index, distance = bvh.find_nearest(point_local)
    if location is None:
        return (False, None, None, -1)
    return (True, location, normal, index)


def closest_surface_hit(context, world_point, targets):
    depsgraph = context.evaluated_depsgraph_get()
    best_hit = None
    best_dist = None

    for target_obj in targets:
        if target_obj is None:
            continue
        obj_eval = target_obj.evaluated_get(depsgraph)

        matrix = target_obj.matrix_world
        matrix_inv = matrix.inverted()
        point_local = matrix_inv @ world_point

        success, loc, normal, _ = _closest_point_on_object(obj_eval, point_local)
        if not success:
            continue

        world_loc = matrix @ loc
        dist = (world_loc - world_point).length
        if best_dist is None or dist < best_dist:
            best_dist = dist
            world_normal = (matrix.to_3x3() @ normal).normalized()
            best_hit = (world_loc + world_normal * SURFACE_OFFSET, world_normal, dist)

    return best_hit


def closest_surface_point(context, world_point, targets):
    hit = closest_surface_hit(context, world_point, targets)
    if hit is None:
        return None
    world_loc, _world_normal, dist = hit
    return (world_loc, dist)


def _embedded_root_point(surface_point, normal_world, embed_depth):
    n = normal_world.normalized() if normal_world.length > 1e-9 else Vector((0.0, 0.0, 1.0))
    depth = max(0.0, embed_depth)
    if depth <= 0.0:
        return surface_point.copy()
    return surface_point - n * depth


def enable_surface_snap(context):
    ts = context.scene.tool_settings
    ts.use_snap = True

    if hasattr(ts, "snap_elements"):
        ts.snap_elements = {'FACE'}
    elif hasattr(ts, "snap_elements_base"):
        ts.snap_elements_base = {'FACE'}

    optional_flags = (
        ("use_snap_align_rotation", True),
        ("use_snap_project", True),
        ("use_snap_backface_culling", True),
    )
    for attr, value in optional_flags:
        if hasattr(ts, attr):
            setattr(ts, attr, value)


# ---------------------------------------------------------------------------
# Curva / mecha
# ---------------------------------------------------------------------------


def apply_stable_twist_setup(curve_obj, context=None):
    curve_obj.data.twist_mode = 'MINIMUM'


def _object_up_reference(obj):
    if obj is None:
        return None
    up = obj.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))
    if up.length < 1e-9:
        return None
    return up.normalized()


def _guide_basis_from_normal(normal, up_reference=None):
    n = normal.normalized() if normal.length > 1e-9 else Vector((0.0, 0.0, 1.0))
    reference = up_reference if up_reference is not None else Vector((0.0, 0.0, 1.0))
    reference = reference.normalized() if reference.length > 1e-9 else Vector((0.0, 0.0, 1.0))

    if abs(n.dot(reference)) > 0.95:
        fallback = reference.cross(Vector((0.0, 1.0, 0.0)))
        if fallback.length < 1e-6:
            fallback = reference.cross(Vector((1.0, 0.0, 0.0)))
        reference = fallback.normalized()

    tangent = n.cross(reference)
    if tangent.length < 1e-9:
        tangent = n.cross(Vector((0.0, 1.0, 0.0)))
    if tangent.length < 1e-9:
        tangent = Vector((1.0, 0.0, 0.0))
    tangent.normalize()

    bitangent = n.cross(tangent)
    if bitangent.length < 1e-9:
        bitangent = Vector((0.0, 1.0, 0.0))
    else:
        bitangent.normalize()

    return tangent, bitangent, n


def _guide_direction_from_normal(normal, angle_radians, up_reference=None):
    tangent, bitangent, _n = _guide_basis_from_normal(normal, up_reference)
    direction = tangent * math.cos(angle_radians) + bitangent * math.sin(angle_radians)
    if direction.length < 1e-9:
        return tangent
    return direction.normalized()


def _growth_strand_points(root_world, normal_world, length, lift, angle_degrees, rng,
                          curve_amount=DEFAULT_GUIDE_CURVE, length_variation=0.0,
                          angle_variation=0.0, mirror_side=False, up_reference=None):
    normal = normal_world.normalized() if normal_world.length > 1e-9 else Vector((0.0, 0.0, 1.0))
    angle_radians = math.radians(angle_degrees)
    angle_radians += math.radians(angle_variation) * rng.uniform(-1.0, 1.0)

    tangent_dir = _guide_direction_from_normal(normal, angle_radians, up_reference)
    if mirror_side:
        tangent_dir = -tangent_dir

    length = max(0.0001, length * rng.uniform(1.0 - length_variation, 1.0 + length_variation))
    curve_amount = max(0.0, min(1.0, curve_amount))

    side_strength = length * 0.10
    lift_strength = max(0.0, lift)

    straight_mid1 = root_world.copy() + normal * (length * (0.28 + 0.12 * lift_strength))
    straight_mid2 = root_world.copy() + normal * (length * (0.62 + 0.08 * lift_strength))
    straight_tip = root_world.copy() + normal * (length * (1.00 + 0.10 * lift_strength))

    curved_mid1 = straight_mid1 + tangent_dir * (side_strength * 0.85)
    curved_mid2 = straight_mid2 + tangent_dir * (side_strength * 0.45)
    curved_tip = straight_tip + tangent_dir * (side_strength * 0.15)

    mid1 = straight_mid1.lerp(curved_mid1, curve_amount)
    mid2 = straight_mid2.lerp(curved_mid2, curve_amount)
    tip = straight_tip.lerp(curved_tip, curve_amount)

    return [root_world.copy(), mid1, mid2, tip]


def _build_mecha_points(root_world, normal_world, length, lift, angle_degrees,
                        curve_amount=DEFAULT_GUIDE_CURVE, up_reference=None):
    rng = random.Random(0)
    return _growth_strand_points(
        root_world=root_world,
        normal_world=normal_world,
        length=length,
        lift=lift,
        angle_degrees=angle_degrees,
        rng=rng,
        curve_amount=curve_amount,
        length_variation=0.0,
        angle_variation=0.0,
        mirror_side=False,
        up_reference=up_reference,
    )


def spline_point_list(spline):
    return spline.bezier_points if spline.type == 'BEZIER' else spline.points


def add_spline_from_points(curve_obj, world_points, radii=None, radius_scale=1.0):
    curve_data = curve_obj.data
    matrix = curve_obj.matrix_world
    matrix_inv = matrix.inverted()

    local_points = [matrix_inv @ p for p in world_points]
    n = len(local_points)

    spline = curve_data.splines.new('BEZIER')
    spline.bezier_points.add(n - 1)

    for i in range(n):
        co = local_points[i]
        bp = spline.bezier_points[i]
        bp.co = co
        base_radius = radii[i] if radii is not None and i < len(radii) else 1.0
        bp.radius = base_radius * radius_scale
        bp.tilt = 0.0
        bp.handle_left_type = 'AUTO'
        bp.handle_right_type = 'AUTO'

    spline.use_cyclic_u = False
    return spline


def strand_radii_by_taper(count, base_radius, taper_amount, mode='TIP'):
    taper_amount = max(0.01, min(1.0, taper_amount))

    if count <= 1:
        return [base_radius] * max(1, count)

    if mode == 'NONE':
        return [base_radius] * count

    radii = []

    if mode == 'TIP':
        for i in range(count):
            t = i / (count - 1)
            factor = 1.0 - t * (1.0 - taper_amount)
            radii.append(base_radius * factor)
        return radii

    if mode == 'ROOT':
        for i in range(count):
            t = i / (count - 1)
            factor = taper_amount + t * (1.0 - taper_amount)
            radii.append(base_radius * factor)
        return radii

    if mode == 'BOTH':
        for i in range(count):
            t = i / (count - 1)
            end_weight = abs(2.0 * t - 1.0)
            factor = taper_amount + (1.0 - taper_amount) * (1.0 - end_weight)
            radii.append(base_radius * factor)
        return radii

    return [base_radius] * count


def _safe_object_rotation_euler(obj):
    try:
        _loc, rot, _scale = obj.matrix_world.decompose()
        return rot.to_euler()
    except Exception:
        return obj.rotation_euler.copy()


def _custom_profile_proxy_name(custom_obj):
    return f"HairProfileProxy_{_safe_name_fragment(custom_obj.name)}"


def _copy_curve_data_scaled_no_location(src_obj, dst_obj, scale_vec):
    src_data = src_obj.data
    dst_data = src_data.copy()
    dst_obj.data = dst_data

    sx, sy, sz = scale_vec.x, scale_vec.y, scale_vec.z

    for spline in dst_data.splines:
        if spline.type == 'BEZIER':
            for bp in spline.bezier_points:
                bp.co.x *= sx
                bp.co.y *= sy
                bp.co.z *= sz
                bp.handle_left.x *= sx
                bp.handle_left.y *= sy
                bp.handle_left.z *= sz
                bp.handle_right.x *= sx
                bp.handle_right.y *= sy
                bp.handle_right.z *= sz
        else:
            for p in spline.points:
                p.co.x *= sx
                p.co.y *= sy
                p.co.z *= sz


def _ensure_custom_profile_proxy(context, custom_obj):
    if custom_obj is None or custom_obj.type != 'CURVE':
        return None

    proxy_name = _custom_profile_proxy_name(custom_obj)
    proxy = bpy.data.objects.get(proxy_name)

    if proxy is None or proxy.type != 'CURVE':
        curve_data = bpy.data.curves.new(proxy_name, type='CURVE')
        proxy = bpy.data.objects.new(proxy_name, curve_data)
        get_profile_collection().objects.link(proxy)
        proxy.hide_render = True
        proxy.hide_viewport = True

    _loc, rot, scale = custom_obj.matrix_world.decompose()
    _copy_curve_data_scaled_no_location(custom_obj, proxy, scale)

    proxy.location = (0.0, 0.0, 0.0)
    proxy.rotation_euler = rot.to_euler()
    proxy.scale = (1.0, 1.0, 1.0)

    normalize_custom_profile_scale(proxy, context.scene.hair_thickness_scale, force=True)

    return proxy


# ---- Proxy de perfil individual por mecha (evita afetar outras mechas) ----


def _local_profile_proxy_name(curve_obj):
    return f"HairProfileProxyLocal_{_safe_name_fragment(curve_obj.name)}"


def _ensure_local_profile_proxy(context, curve_obj, base_obj):
    """Cria/atualiza um proxy do perfil exclusivo para 'curve_obj', copiando a forma
    do perfil compartilhado (base_obj) mas mantendo escala independente. Assim, ajustar
    a espessura de uma mecha via a ferramenta 'S' na criação não altera o objeto de
    perfil global (que é compartilhado por todas as outras mechas do mesmo tipo de perfil)."""
    if base_obj is None:
        return None

    proxy_name = _local_profile_proxy_name(curve_obj)
    proxy = bpy.data.objects.get(proxy_name)

    if proxy is None or proxy.type != 'CURVE':
        curve_data = bpy.data.curves.new(proxy_name, type='CURVE')
        proxy = bpy.data.objects.new(proxy_name, curve_data)
        get_profile_collection().objects.link(proxy)
        proxy.hide_render = True
        proxy.hide_viewport = True

    # Copia a geometria do perfil base "as-is" (sem herdar a escala do base_obj),
    # e reaplica só a nossa própria escala local em seguida.
    new_data = base_obj.data.copy()
    proxy.data = new_data
    proxy.location = (0.0, 0.0, 0.0)
    proxy.rotation_euler = (0.0, 0.0, 0.0)

    proxy["hair_profile_base_scale"] = get_profile_base_scale(base_obj)

    local_scale = curve_obj.get("hair_thickness_local_scale", None)
    apply_profile_scale(proxy, local_scale if local_scale is not None else 1.0)

    return proxy


def resolve_bevel_object(context):
    scene = context.scene
    kind = scene.hair_profile_kind

    if kind == 'CUSTOM':
        custom = scene.hair_profile_custom
        if custom is not None:
            proxy = _ensure_custom_profile_proxy(context, custom)
            if proxy is not None:
                return proxy
        return get_or_create_profile('ROUND', scene.hair_profile_segments, scene.hair_profile_smooth)

    if kind == 'ROUND':
        return get_or_create_profile('ROUND', scene.hair_profile_segments, scene.hair_profile_smooth)

    if kind == 'STAR':
        return get_or_create_profile('STAR', smooth=scene.hair_profile_smooth)

    if kind == 'FLAT':
        return get_or_create_profile(
            'FLAT', smooth=scene.hair_profile_smooth,
            flat_depth=scene.hair_profile_flat_arc_depth,
            flat_segments=scene.hair_profile_flat_segments,
        )

    if kind == 'CLUMP':
        return get_or_create_profile(
            'CLUMP', smooth=scene.hair_profile_smooth,
            clump_count=scene.hair_profile_clump_count,
            clump_spread=scene.hair_profile_clump_spread,
            clump_strand_radius=scene.hair_profile_clump_strand_radius,
        )

    return get_or_create_profile(kind)


def apply_bevel_settings(curve_data, context, curve_obj=None):
    base_obj = resolve_bevel_object(context)

    local_scale = curve_obj.get("hair_thickness_local_scale", None) if curve_obj is not None else None

    curve_data.bevel_mode = 'OBJECT'
    if curve_obj is not None and local_scale is not None:
        proxy = _ensure_local_profile_proxy(context, curve_obj, base_obj)
        curve_data.bevel_object = proxy if proxy is not None else base_obj
    else:
        curve_data.bevel_object = base_obj


def apply_curve_style(obj, context):
    apply_stable_twist_setup(obj, context)
    apply_bevel_settings(obj.data, context, curve_obj=obj)
    obj.data.use_fill_caps = bool(context.scene.hair_close_tips)
    return True


def _select_only(context, obj):
    for other in list(context.selected_objects):
        if other is not obj:
            other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _active_curve_object(context):
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return None
    return obj


def _ensure_object_mode():
    try:
        bpy.ops.object.mode_set(mode='OBJECT')
    except RuntimeError:
        pass


def _enter_edit_mode():
    try:
        bpy.ops.object.mode_set(mode='EDIT')
    except RuntimeError:
        pass


def resolve_safe_collection(context):
    layer_coll = context.view_layer.active_layer_collection
    if layer_coll is not None and not getattr(layer_coll, "exclude", False):
        return layer_coll.collection
    return context.scene.collection


def ensure_object_in_view_layer(context, obj):
    if obj.name in context.view_layer.objects:
        return
    safe_coll = resolve_safe_collection(context)
    if obj.name not in safe_coll.objects:
        safe_coll.objects.link(obj)


# ---------------------------------------------------------------------------
# Dados de guia por fio (raiz/normal/peso), usados para reconstruir splines
# ---------------------------------------------------------------------------


def _get_guide_data(obj):
    raw = obj.get("hair_guide_data")
    if not raw:
        return []
    result = []
    for entry in raw:
        try:
            root = list(entry["root"])
            normal = list(entry["normal"])
        except (KeyError, TypeError):
            continue
        up_raw = entry.get("up") if hasattr(entry, "get") else None
        result.append({
            "root": root,
            "normal": normal,
            "up": list(up_raw) if up_raw is not None else None,
            "weight": entry.get("weight", 1.0) if hasattr(entry, "get") else 1.0,
        })
    return result


def _set_guide_data(obj, data):
    obj["hair_guide_data"] = data


def _clear_guide_data(obj):
    obj["hair_guide_data"] = []


def _append_guide_entry(obj, root_world, normal_world, up_reference=None, weight=1.0):
    data = _get_guide_data(obj)
    data.append({
        "root": [root_world.x, root_world.y, root_world.z],
        "normal": [normal_world.x, normal_world.y, normal_world.z],
        "up": [up_reference.x, up_reference.y, up_reference.z] if up_reference is not None else None,
        "weight": weight,
    })
    _set_guide_data(obj, data)


def _pop_guide_entry(obj):
    data = _get_guide_data(obj)
    if data:
        data.pop()
        _set_guide_data(obj, data)


def _new_mecha_object_at(context, root_world, normal_world, length, lift, angle_degrees, tip_taper,
                         curve_amount=DEFAULT_GUIDE_CURVE, existing_obj=None, target=None):
    scene = context.scene
    embedded_root = _embedded_root_point(root_world, normal_world, scene.hair_root_embed_depth)
    up_reference = _object_up_reference(target)
    world_points = _build_mecha_points(
        embedded_root,
        normal_world,
        length,
        lift,
        angle_degrees,
        curve_amount=curve_amount,
        up_reference=up_reference,
    )

    _ensure_object_mode()

    if existing_obj is not None and existing_obj.name in bpy.data.objects and existing_obj.type == 'CURVE':
        obj = existing_obj
        curve_data = obj.data
    else:
        curve_data = bpy.data.curves.new(HAIR_MECHA_PREFIX, type='CURVE')
        curve_data.dimensions = '3D'
        curve_data.use_radius = True
        curve_data.resolution_u = 12

        obj = bpy.data.objects.new(HAIR_MECHA_PREFIX, curve_data)
        obj.location = embedded_root
        obj["hair_click_mecha_object"] = True
        resolve_safe_collection(context).objects.link(obj)
        ensure_object_in_view_layer(context, obj)
        context.view_layer.update()

    tip_taper_clamped = max(0.02, min(1.0, tip_taper))
    taper_mode = context.scene.hair_taper_mode
    radii = strand_radii_by_taper(len(world_points), 1.0, tip_taper_clamped, mode=taper_mode)
    add_spline_from_points(
        obj,
        world_points,
        radii=radii,
        radius_scale=context.scene.hair_thickness_scale,
    )
    _append_guide_entry(obj, embedded_root, normal_world, up_reference=up_reference, weight=1.0)
    apply_curve_style(obj, context)

    return obj


def _delete_object_and_data(obj):
    if obj is None:
        return
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        try:
            bpy.data.curves.remove(data)
        except Exception:
            pass


def _remove_last_spline_from_curve_object(obj):
    if obj is None or obj.type != 'CURVE' or not obj.data.splines:
        return False

    curve_data = obj.data
    last_spline = curve_data.splines[-1]
    curve_data.splines.remove(last_spline)
    _pop_guide_entry(obj)

    if len(curve_data.splines) == 0:
        _delete_object_and_data(obj)
    else:
        curve_data.update_tag()
    return True


def _create_mecha_curve(context):
    scene = context.scene
    target = scene.hair_surface_target
    if target is None:
        return None, "Escolha uma superfície primeiro"

    cursor_point = scene.cursor.location.copy()
    hit = closest_surface_hit(context, cursor_point, [target])
    if hit is None:
        hit = closest_surface_hit(context, target.matrix_world.translation.copy(), [target])
    if hit is None:
        return None, "Não foi possível encontrar a superfície da cabeça"

    surface_root, normal_world, _dist = hit
    obj = _new_mecha_object_at(
        context, surface_root, normal_world,
        scene.hair_guide_length, scene.hair_guide_lift, scene.hair_guide_angle,
        scene.hair_guide_tip_taper, curve_amount=scene.hair_guide_curve_amount,
        target=target,
    )

    _select_only(context, obj)
    context.view_layer.update()

    return obj, None


def _snap_active_curve_root_to_surface(context, obj):
    target = context.scene.hair_surface_target
    if target is None:
        return False, "Escolha uma superfície primeiro"

    if not obj.data.splines:
        return False, "A curva ativa não tem mechas"

    spline = obj.data.splines[0]
    if spline.type != 'BEZIER' or not spline.bezier_points:
        return False, "A mecha ativa precisa ser uma curva Bezier"

    root_local = spline.bezier_points[0].co.copy()
    root_world = obj.matrix_world @ root_local
    hit = closest_surface_hit(context, root_world, [target])
    if hit is None:
        return False, "Não foi possível encontrar a superfície para snap"

    snapped_root, snapped_normal, _dist = hit
    snapped_root = _embedded_root_point(snapped_root, snapped_normal, context.scene.hair_root_embed_depth)
    delta = snapped_root - root_world
    obj.matrix_world.translation += delta

    guide_data = _get_guide_data(obj)
    if guide_data:
        guide_data[0]["root"] = [snapped_root.x, snapped_root.y, snapped_root.z]
        guide_data[0]["normal"] = [snapped_normal.x, snapped_normal.y, snapped_normal.z]
        _set_guide_data(obj, guide_data)

    return True, None


# ---------------------------------------------------------------------------
# Crescimento pela pintura / Weight Paint
# ---------------------------------------------------------------------------


def ensure_growth_vertex_group(target_obj, group_name):
    group_name = (group_name or "").strip() or "HairGrowth"
    vg = target_obj.vertex_groups.get(group_name)
    if vg is None:
        vg = target_obj.vertex_groups.new(name=group_name)
    return vg


def get_selected_growth_vertex_group_name(scene):
    selected = (scene.hair_growth_vertex_group or "").strip()
    if selected:
        return selected
    new_name = (scene.hair_new_vertex_group_name or "").strip()
    if new_name:
        return new_name
    return "HairGrowth"


def set_active_vertex_group(target_obj, group_name):
    vg = target_obj.vertex_groups.get((group_name or "").strip())
    if vg is None:
        return None
    try:
        target_obj.vertex_groups.active_index = vg.index
    except Exception:
        pass
    return vg


def _get_vertex_weight(mesh_obj, vertex_index, group_index):
    try:
        for g in mesh_obj.data.vertices[vertex_index].groups:
            if g.group == group_index:
                return g.weight
    except (AttributeError, IndexError):
        pass
    return 0.0


def _triangle_area_world(v0, v1, v2):
    return ((v1 - v0).cross(v2 - v0)).length * 0.5


def _sample_point_in_triangle(v0, v1, v2, rng):
    r1 = math.sqrt(rng.random())
    r2 = rng.random()
    a = 1.0 - r1
    b = r1 * (1.0 - r2)
    c = r1 * r2
    return (v0 * a) + (v1 * b) + (v2 * c)


def _mesh_weighted_triangle_records(context, mesh_obj, group_name, weight_threshold=0.0):
    depsgraph = context.evaluated_depsgraph_get()
    obj_eval = mesh_obj.evaluated_get(depsgraph)

    try:
        temp_mesh = obj_eval.to_mesh()
    except RuntimeError:
        return []

    if temp_mesh is None:
        return []

    temp_mesh.calc_loop_triangles()
    if not temp_mesh.loop_triangles:
        obj_eval.to_mesh_clear()
        return []

    vg = mesh_obj.vertex_groups.get(group_name)
    group_index = vg.index if vg is not None else -1
    matrix = mesh_obj.matrix_world

    records = []
    for tri in temp_mesh.loop_triangles:
        indices = tri.vertices
        local_verts = [temp_mesh.vertices[i].co.copy() for i in indices]
        world_verts = [matrix @ v for v in local_verts]

        area = _triangle_area_world(world_verts[0], world_verts[1], world_verts[2])
        if area <= 1e-12:
            continue

        if group_index >= 0:
            weights = [max(0.0, _get_vertex_weight(mesh_obj, i, group_index)) for i in indices]
            weight = sum(weights) / 3.0
        else:
            weight = 1.0

        if weight < weight_threshold:
            continue

        score = area * max(0.0, weight)
        if score <= 1e-12:
            continue

        world_normal = (matrix.to_3x3() @ tri.normal).normalized()
        centroid = (world_verts[0] + world_verts[1] + world_verts[2]) / 3.0
        records.append({
            "score": score,
            "verts": world_verts,
            "normal": world_normal,
            "centroid": centroid,
            "weight": max(0.0, min(1.0, weight)),
        })

    obj_eval.to_mesh_clear()
    return records


def _weighted_pick(records, rng):
    total = 0.0
    for record in records:
        total += record["score"]
    if total <= 0.0:
        return None

    pick = rng.random() * total
    accum = 0.0
    for record in records:
        accum += record["score"]
        if accum >= pick:
            return record
    return records[-1]


def _distance_to_existing_roots(existing_roots, candidate, min_spacing):
    if min_spacing <= 0.0:
        return True
    min_spacing_sq = min_spacing * min_spacing
    for p in existing_roots:
        if (p - candidate).length_squared < min_spacing_sq:
            return False
    return True


def _count_nearby_roots(existing_roots, candidate, radius):
    if radius <= 0.0 or not existing_roots:
        return 0
    radius_sq = radius * radius
    count = 0
    for p in existing_roots:
        if (p - candidate).length_squared < radius_sq:
            count += 1
    return count


def _pick_root_with_spacing(records, rng, existing_roots, min_spacing, attempts=8, fill_mode=False):
    if not records:
        return None

    occupancy_radius = max(min_spacing * 3.0, 1e-5)
    sample_count = max(1, attempts)

    best_candidate = None
    best_occupancy = None

    for _ in range(sample_count if not fill_mode else max(sample_count, 3)):
        base = _weighted_pick(records, rng)
        if base is None:
            break

        verts = base["verts"]
        normal = base["normal"]
        candidate = _sample_point_in_triangle(verts[0], verts[1], verts[2], rng)
        candidate = candidate + normal * SURFACE_OFFSET

        if not _distance_to_existing_roots(existing_roots, candidate, min_spacing):
            continue

        if not fill_mode:
            return candidate, normal, base

        occupancy = _count_nearby_roots(existing_roots, candidate, occupancy_radius)
        if best_occupancy is None or occupancy < best_occupancy:
            best_occupancy = occupancy
            best_candidate = (candidate, normal, base)
            if occupancy == 0:
                break

    if best_candidate is not None:
        return best_candidate

    relaxed_spacing = min_spacing * 0.5
    for _ in range(sample_count):
        base = _weighted_pick(records, rng)
        if base is None:
            break

        verts = base["verts"]
        normal = base["normal"]
        candidate = _sample_point_in_triangle(verts[0], verts[1], verts[2], rng)
        candidate = candidate + normal * SURFACE_OFFSET

        if _distance_to_existing_roots(existing_roots, candidate, relaxed_spacing):
            return candidate, normal, base

    return None


def _growth_object_name(target_obj, group_name):
    target_fragment = _safe_name_fragment(target_obj.name if target_obj else "Target")
    group_fragment = _safe_name_fragment(group_name or "HairGrowth")
    return f"{HAIR_GROWTH_PREFIX}_{target_fragment}_{group_fragment}"


def _safe_name_fragment(text):
    text = str(text or "").strip()
    if not text:
        return "Unnamed"
    chars = []
    for ch in text:
        if ch.isalnum() or ch in {"_", "-"}:
            chars.append(ch)
        else:
            chars.append("_")
    cleaned = "".join(chars).strip("_")
    return cleaned or "Unnamed"


def _generate_mirror_point(target_obj, world_point):
    matrix = target_obj.matrix_world
    matrix_inv = matrix.inverted()
    local_point = matrix_inv @ world_point
    mirrored_local = Vector((-local_point.x, local_point.y, local_point.z))
    return matrix @ mirrored_local


def _mirror_direction(target_obj, world_direction):
    matrix_3x3 = target_obj.matrix_world.to_3x3()
    matrix_3x3_inv = matrix_3x3.inverted()
    local_dir = matrix_3x3_inv @ world_direction
    mirrored_local = Vector((-local_dir.x, local_dir.y, local_dir.z))
    mirrored_world = matrix_3x3 @ mirrored_local
    if mirrored_world.length > 1e-9:
        mirrored_world.normalize()
    return mirrored_world


def _mirror_record_record(target_obj, record):
    mirrored = {
        "score": record["score"],
        "verts": [_generate_mirror_point(target_obj, v) for v in record["verts"]],
        "normal": _mirror_direction(target_obj, record["normal"]),
        "centroid": _generate_mirror_point(target_obj, record["centroid"]),
        "weight": record["weight"],
    }
    return mirrored


def _remove_existing_growth_object(context, target_obj=None, group_name=None):
    scene = context.scene

    if target_obj is None or group_name is None:
        existing_name = scene.hair_growth_result_object.strip()
        if not existing_name:
            return None
        obj = bpy.data.objects.get(existing_name)
        if obj is None:
            scene.hair_growth_result_object = ""
        return obj

    obj_name = _growth_object_name(target_obj, group_name)
    obj = bpy.data.objects.get(obj_name)
    return obj


def _create_growth_from_paint(context):
    scene = context.scene
    target = scene.hair_surface_target
    if target is None:
        return None, "Escolha uma superfície primeiro"
    if target.type != 'MESH':
        return None, "A superfície precisa ser uma malha"

    group_name = get_selected_growth_vertex_group_name(scene)
    vg = target.vertex_groups.get(group_name)
    if vg is None:
        vg = ensure_growth_vertex_group(target, group_name)

    weight_threshold = max(0.0, min(0.999, scene.hair_growth_weight_threshold))
    records = _mesh_weighted_triangle_records(context, target, vg.name, weight_threshold=weight_threshold)
    if not records:
        return None, "Nenhuma área pintada acima do peso mínimo definido"

    use_mirror = bool(scene.hair_growth_mirror_other_side)
    if use_mirror:
        mirrored_records = [_mirror_record_record(target, r) for r in records]
        records = records + mirrored_records

    rng = random.Random(scene.hair_growth_seed)
    count = max(1, scene.hair_growth_count)
    base_length = max(0.001, scene.hair_guide_length)
    min_spacing = max(0.0, scene.hair_growth_min_spacing)
    spacing_attempts = max(1, scene.hair_growth_spacing_attempts)
    fill_mode = bool(scene.hair_growth_fill_mode)

    weight_affects_length = bool(scene.hair_growth_weight_affects_length)
    weight_affects_thickness = bool(scene.hair_growth_weight_affects_thickness)
    length_weight_min = max(0.05, min(1.0, scene.hair_growth_length_weight_min))
    thickness_weight_min = max(0.05, min(1.0, scene.hair_growth_thickness_weight_min))
    tip_taper = max(0.05, min(1.0, scene.hair_growth_tip_taper))
    weight_range = max(1e-6, 1.0 - weight_threshold)
    embed_depth = max(0.0, scene.hair_root_embed_depth)
    up_reference = _object_up_reference(target)

    _ensure_object_mode()

    obj_name = _growth_object_name(target, vg.name)
    existing = bpy.data.objects.get(obj_name)

    if existing is not None and existing.type == 'CURVE':
        obj = existing
        curve_data = obj.data
        curve_data.splines.clear()
    else:
        curve_data = bpy.data.curves.new(obj_name, type='CURVE')
        curve_data.dimensions = '3D'
        curve_data.use_radius = True
        curve_data.resolution_u = 12

        obj = bpy.data.objects.new(obj_name, curve_data)
        obj.location = (0.0, 0.0, 0.0)
        resolve_safe_collection(context).objects.link(obj)
        ensure_object_in_view_layer(context, obj)

    obj["hair_growth_target_name"] = target.name
    obj["hair_growth_group_name"] = vg.name
    _clear_guide_data(obj)

    existing_roots = []
    accepted = 0
    max_total_attempts = max(count * 8, count)

    for _ in range(max_total_attempts):
        if accepted >= count:
            break

        picked = _pick_root_with_spacing(
            records, rng, existing_roots, min_spacing,
            attempts=spacing_attempts, fill_mode=fill_mode,
        )
        if picked is None:
            base_record = _weighted_pick(records, rng)
            if base_record is None:
                break
            verts = base_record["verts"]
            normal = base_record["normal"]
            root = _sample_point_in_triangle(verts[0], verts[1], verts[2], rng)
            root = root + normal * SURFACE_OFFSET
        else:
            root, normal, base_record = picked

        if not _distance_to_existing_roots(existing_roots, root, min_spacing * 0.35):
            continue

        local_weight = base_record["weight"]
        weight_norm = max(0.0, min(1.0, (local_weight - weight_threshold) / weight_range))

        length_factor = 1.0
        if weight_affects_length:
            length_factor = length_weight_min + (1.0 - length_weight_min) * weight_norm
        effective_length = max(0.0005, base_length * length_factor)

        thickness_root_factor = 1.0
        if weight_affects_thickness:
            thickness_root_factor = thickness_weight_min + (1.0 - thickness_weight_min) * weight_norm

        spline_root = _embedded_root_point(root, normal, embed_depth)
        points = _growth_strand_points(
            spline_root,
            normal,
            effective_length,
            scene.hair_guide_lift,
            scene.hair_guide_angle,
            rng,
            curve_amount=scene.hair_guide_curve_amount,
            length_variation=scene.hair_growth_length_variation,
            angle_variation=scene.hair_growth_angle_variation,
            mirror_side=False,
            up_reference=up_reference,
        )
        radii = strand_radii_by_taper(
            len(points),
            thickness_root_factor,
            tip_taper,
            mode=scene.hair_taper_mode,
        )
        add_spline_from_points(obj, points, radii=radii)
        _append_guide_entry(obj, spline_root, normal, up_reference=up_reference, weight=local_weight)
        existing_roots.append(root)
        accepted += 1

    apply_curve_style(obj, context)
    scene.hair_growth_result_object = obj.name

    _select_only(context, obj)
    context.view_layer.update()
    return obj, None


# ---------------------------------------------------------------------------
# Auto-aplicação de estilo (perfil / espessura / afinação / tampas)
# ---------------------------------------------------------------------------


def _is_hair_curve_object(obj):
    if obj is None or obj.type != 'CURVE':
        return False
    return obj.name.startswith(HAIR_MECHA_PREFIX) or obj.name.startswith(HAIR_GROWTH_PREFIX)


def _active_hair_curve_object(context):
    obj = context.active_object
    return obj if _is_hair_curve_object(obj) else None


def _style_scope_targets(context):
    scene = context.scene
    if scene.hair_style_apply_scope == 'ALL':
        return [o for o in scene.objects if _is_hair_curve_object(o)]

    obj = _active_hair_curve_object(context)
    return [obj] if obj is not None else []


def _apply_style_to_curve(obj, context):
    apply_curve_style(obj, context)

    # Se esta mecha tem uma espessura local (ajustada com a ferramenta "S" na
    # criação por clique), ela usa seu proprio proxy de perfil e não deve ser
    # sobrescrita pelo slider global "Espessura" da cena.
    if obj.get("hair_thickness_local_scale") is not None:
        return

    bevel_obj = obj.data.bevel_object
    if bevel_obj is not None:
        apply_profile_scale(bevel_obj, context.scene.hair_thickness_scale)


def _auto_apply_style(context):
    for obj in _style_scope_targets(context):
        if obj is not None and obj.name in bpy.data.objects:
            _apply_style_to_curve(obj, context)


def _on_style_property_change(self, context):
    _auto_apply_style(context)


def _on_profile_custom_change(self, context):
    custom = self.hair_profile_custom
    if custom is not None:
        normalize_custom_profile_scale(custom, self.hair_thickness_scale, force=False)
    _auto_apply_style(context)


# ---------------------------------------------------------------------------
# Reconstrução ao vivo da guia (comprimento / elevação / ângulo / curvatura / afinar)
# ---------------------------------------------------------------------------


def _rebuild_curve_from_guide_data(obj, context):
    """Reconstrói os pontos (e raio) de cada spline do objeto usando os dados de
    guia salvos (raiz/normal/peso de cada fio) e os valores atuais dos sliders de
    guia da cena. Retorna a quantidade de splines efetivamente reconstruídas."""
    guide_data = _get_guide_data(obj)
    if not guide_data:
        return 0

    curve_data = obj.data
    splines = curve_data.splines
    count_to_process = min(len(splines), len(guide_data))
    if count_to_process == 0:
        return 0

    scene = context.scene
    base_length = max(0.001, scene.hair_guide_length)
    lift = scene.hair_guide_lift
    angle = scene.hair_guide_angle
    curve_amount = scene.hair_guide_curve_amount
    tip_taper = max(0.02, min(1.0, scene.hair_guide_tip_taper))
    taper_mode = scene.hair_taper_mode

    weight_threshold = max(0.0, min(0.999, scene.hair_growth_weight_threshold))
    weight_range = max(1e-6, 1.0 - weight_threshold)
    weight_affects_length = bool(scene.hair_growth_weight_affects_length)
    weight_affects_thickness = bool(scene.hair_growth_weight_affects_thickness)
    length_weight_min = max(0.05, min(1.0, scene.hair_growth_length_weight_min))
    thickness_weight_min = max(0.05, min(1.0, scene.hair_growth_thickness_weight_min))

    # Mesma convenção usada na criação: mechas por clique já "carimbam" a
    # espessura global no raio da própria curva; mechas de crescimento deixam
    # isso a cargo do objeto de bevel (para não aplicar a escala em dobro).
    radius_scale = scene.hair_thickness_scale if obj.name.startswith(HAIR_MECHA_PREFIX) else 1.0

    matrix_inv = obj.matrix_world.inverted()
    rng = random.Random(0)
    processed = 0

    for i in range(count_to_process):
        spline = splines[i]
        if spline.type != 'BEZIER' or not spline.bezier_points:
            continue

        entry = guide_data[i]
        root = Vector(entry["root"])
        normal = Vector(entry["normal"])
        up = Vector(entry["up"]) if entry.get("up") is not None else None
        weight = entry.get("weight", 1.0)

        weight_norm = max(0.0, min(1.0, (weight - weight_threshold) / weight_range))
        length_factor = 1.0
        if weight_affects_length:
            length_factor = length_weight_min + (1.0 - length_weight_min) * weight_norm
        effective_length = max(0.0005, base_length * length_factor)

        thickness_root_factor = 1.0
        if weight_affects_thickness:
            thickness_root_factor = thickness_weight_min + (1.0 - thickness_weight_min) * weight_norm

        world_points = _growth_strand_points(
            root, normal, effective_length, lift, angle, rng,
            curve_amount=curve_amount,
            length_variation=0.0,
            angle_variation=0.0,
            mirror_side=False,
            up_reference=up,
        )
        radii = strand_radii_by_taper(len(world_points), thickness_root_factor, tip_taper, mode=taper_mode)

        bezier_points = spline.bezier_points
        point_count = min(len(bezier_points), len(world_points))
        for j in range(point_count):
            bp = bezier_points[j]
            bp.co = matrix_inv @ world_points[j]
            bp.radius = radii[j] * radius_scale
            bp.handle_left_type = 'AUTO'
            bp.handle_right_type = 'AUTO'

        processed += 1

    curve_data.update_tag()
    return processed


def _apply_guide_to_targets(context, targets):
    total = 0
    for obj in targets:
        if obj is None or obj.name not in bpy.data.objects:
            continue
        total += _rebuild_curve_from_guide_data(obj, context)
    context.view_layer.update()
    return total


def _on_guide_property_change(self, context):
    if not context.scene.hair_guide_live_update:
        return
    targets = _style_scope_targets(context)
    if targets:
        _apply_guide_to_targets(context, targets)
