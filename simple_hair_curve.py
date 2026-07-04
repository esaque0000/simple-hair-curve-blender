bl_info = {
    "name": "Simple Hair Curve",
    "author": "Esaque",
    "version": (0, 9, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Hair",
    "description": "Cabelo como curva desenhada via raycast (sempre grudada na superfície) com perfis de estilização.",
    "category": "Curve",
}

import bpy
import math
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from bpy_extras import view3d_utils


PROFILE_COLLECTION_NAME = "Hair Profiles"


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

    if smooth:
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


def make_flat_profile(width=0.02):
    half = width * 0.5
    pts = [(-half, 0.0), (half, 0.0)]
    return _new_curve_object("HairProfile_Flat", pts, cyclic=False)


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


PROFILE_BUILDERS = {
    'ROUND': make_round_profile,
    'FLAT': make_flat_profile,
    'SQUARE': make_square_profile,
    'STAR': make_star_profile,
}


def get_or_create_profile(kind, segments=8, smooth=True):
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

    name_map = {
        'FLAT': "HairProfile_Flat",
        'SQUARE': "HairProfile_Square",
    }
    existing = bpy.data.objects.get(name_map[kind])
    if existing:
        return existing
    return PROFILE_BUILDERS[kind]()


TARGET_PROFILE_RADIUS = 0.01


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


def resolve_bevel_object(context):
    scene = context.scene
    kind = scene.hair_profile_kind
    if kind == 'CUSTOM':
        custom = scene.hair_profile_custom
        if custom is not None:
            normalize_custom_profile_scale(custom, scene.hair_thickness_scale)
            return custom
        return get_or_create_profile('ROUND', scene.hair_profile_segments, scene.hair_profile_smooth)
    if kind == 'ROUND':
        return get_or_create_profile('ROUND', scene.hair_profile_segments, scene.hair_profile_smooth)
    if kind == 'STAR':
        return get_or_create_profile('STAR', smooth=scene.hair_profile_smooth)
    return get_or_create_profile(kind)


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


SURFACE_OFFSET = 0.0005
STABILIZER_MAX_WINDOW = 40


HAIR_STRAND_PREFIX = "HairStrand"


def raycast_targets(context, coord, targets):
    region = context.region
    rv3d = context.region_data
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    ray_dir = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

    depsgraph = context.evaluated_depsgraph_get()
    best_hit = None
    best_dist = None

    for target_obj in targets:
        if target_obj is None:
            continue
        obj_eval = target_obj.evaluated_get(depsgraph)

        matrix = target_obj.matrix_world
        matrix_inv = matrix.inverted()
        origin_local = matrix_inv @ ray_origin
        dir_local = (matrix_inv.to_3x3() @ ray_dir).normalized()

        success, loc, normal, face_index = obj_eval.ray_cast(origin_local, dir_local)
        if not success:
            continue

        world_loc = matrix @ loc
        dist = (world_loc - ray_origin).length
        if best_dist is None or dist < best_dist:
            best_dist = dist
            world_normal = (matrix.to_3x3() @ normal).normalized()
            best_hit = world_loc + world_normal * SURFACE_OFFSET

    return best_hit


def collect_existing_hair_objects(exclude=None):
    result = []
    for obj in bpy.data.objects:
        if obj is exclude:
            continue
        if obj.type == 'CURVE' and obj.name.startswith(HAIR_STRAND_PREFIX):
            result.append(obj)
    return result


def sample_point(context, coord, targets, last_point):
    hit = raycast_targets(context, coord, targets)
    if hit is not None:
        return hit

    region = context.region
    rv3d = context.region_data
    if last_point is not None:
        depth_ref = last_point
    else:
        depth_ref = targets[0].matrix_world.translation if targets else Vector((0, 0, 0))
    return view3d_utils.region_2d_to_location_3d(region, rv3d, coord, depth_ref)


def add_spline_from_points(curve_obj, world_points):
    curve_data = curve_obj.data
    matrix_inv = curve_obj.matrix_world.inverted()

    spline = curve_data.splines.new('POLY')
    spline.points.add(len(world_points) - 1)
    for i, p in enumerate(world_points):
        local = matrix_inv @ p
        spline.points[i].co = (local.x, local.y, local.z, 1.0)
    return spline


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


def _perpendicular_distance(point, line_start, line_end):
    line_vec = line_end - line_start
    length_sq = line_vec.length_squared
    if length_sq < 1e-12:
        return (point - line_start).length
    t = (point - line_start).dot(line_vec) / length_sq
    t = max(0.0, min(1.0, t))
    projection = line_start + line_vec * t
    return (point - projection).length


def simplify_stroke_points(points, epsilon):
    n = len(points)
    if epsilon <= 0.0 or n < 3:
        return points

    keep = [False] * n
    keep[0] = True
    keep[-1] = True
    stack = [(0, n - 1)]

    while stack:
        start_i, end_i = stack.pop()
        if end_i <= start_i + 1:
            continue
        start_pt = points[start_i]
        end_pt = points[end_i]
        max_dist = -1.0
        max_idx = -1
        for i in range(start_i + 1, end_i):
            d = _perpendicular_distance(points[i], start_pt, end_pt)
            if d > max_dist:
                max_dist = d
                max_idx = i
        if max_dist > epsilon:
            keep[max_idx] = True
            stack.append((start_i, max_idx))
            stack.append((max_idx, end_i))

    return [p for p, k in zip(points, keep) if k]


def apply_taper_to_spline(spline, fraction, tip_radius, mode):
    points = spline.points
    n = len(points)
    if n < 2 or mode == 'OFF':
        reset_spline_radius(spline)
        return

    for point in points:
        point.radius = 1.0

    max_taper = n // 2 if mode == 'BOTH' else n
    taper_count = min(max_taper, max(1, round(n * fraction)))
    denom = max(1, taper_count - 1)

    if mode in ('TIP', 'BOTH'):
        start_idx = n - taper_count
        for i in range(start_idx, n):
            t = (i - start_idx) / denom
            points[i].radius = 1.0 + t * (tip_radius - 1.0)

    if mode in ('ROOT', 'BOTH'):
        for i in range(taper_count):
            t = (taper_count - 1 - i) / denom
            points[i].radius = 1.0 + t * (tip_radius - 1.0)


def reset_spline_radius(spline):
    for point in spline.points:
        point.radius = 1.0


_UNIFORM_SHADER_CACHE = None

STROKE_PREVIEW_COLOR = (1.0, 0.55, 0.1, 0.95)
STROKE_PREVIEW_POINT_COLOR = (1.0, 0.9, 0.2, 1.0)


def get_uniform_color_shader():
    global _UNIFORM_SHADER_CACHE
    if _UNIFORM_SHADER_CACHE is not None:
        return _UNIFORM_SHADER_CACHE
    for name in ('UNIFORM_COLOR', '3D_UNIFORM_COLOR'):
        try:
            _UNIFORM_SHADER_CACHE = gpu.shader.from_builtin(name)
            return _UNIFORM_SHADER_CACHE
        except (ValueError, Exception):
            continue
    return None


def draw_stroke_preview(points):
    if not points:
        return

    shader = get_uniform_color_shader()
    if shader is None:
        return

    coords = [tuple(p) for p in points]

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')

    if len(coords) >= 2:
        gpu.state.line_width_set(3.0)
        batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": coords})
        shader.bind()
        shader.uniform_float("color", STROKE_PREVIEW_COLOR)
        batch.draw(shader)
        gpu.state.line_width_set(1.0)

    gpu.state.point_size_set(9.0)
    start_batch = batch_for_shader(shader, 'POINTS', {"pos": [coords[0]]})
    shader.bind()
    shader.uniform_float("color", STROKE_PREVIEW_POINT_COLOR)
    start_batch.draw(shader)

    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


class HAIR_OT_draw_strand(bpy.types.Operator):
    bl_idname = "hair.draw_strand"
    bl_label = "Desenhar Mecha"
    bl_options = {'REGISTER', 'UNDO'}

    NAV_PASSTHROUGH = {
        'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE',
        'TRACKPADPAN', 'TRACKPADZOOM',
        'NUMPAD_1', 'NUMPAD_2', 'NUMPAD_3', 'NUMPAD_4',
        'NUMPAD_6', 'NUMPAD_7', 'NUMPAD_8', 'NUMPAD_9',
        'NUMPAD_5', 'NUMPAD_PERIOD',
    }

    @classmethod
    def poll(cls, context):
        return context.scene.hair_surface_target is not None

    def invoke(self, context, event):
        self.target = context.scene.hair_surface_target
        self.strand_count = 0
        self.spline_history = []  # (curve_obj, spline) confirmados nesta sessão, pra Ctrl+Z

        # se o objeto ativo no viewport já for uma mecha desenhada por
        # esta ferramenta, continua adicionando splines nela; senão,
        # cada sessão cria um objeto novo (sem depender de nenhum
        # estado "lembrado" entre uma sessão e outra)
        active_obj = context.active_object
        if (active_obj is not None and active_obj.type == 'CURVE'
                and active_obj.name.startswith(HAIR_STRAND_PREFIX)):
            self.curve_obj = active_obj
        else:
            self.curve_obj = None

        self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_callback, (), 'WINDOW', 'POST_VIEW'
        )

        started_in_viewport = (
            context.area is not None and context.area.type == 'VIEW_3D'
            and context.region is not None and context.region.type == 'WINDOW'
        )
        if started_in_viewport:
            # veio de um clique de verdade na viewport (ex: ferramenta
            # "Cabelo"): já começa a primeira mecha a partir desse clique
            self._start_stroke(context, event)
        else:
            # veio de fora da viewport (ex: botão "Desenhar Mecha (1
            # traço)" do painel): NÃO começa nenhum traço ainda — sem
            # isso, um simples mover do mouse sobre a cabeça (sem
            # clicar) já desenhava uma linha guia sozinha, porque a
            # sessão pensava que já estava "no meio de um traço". Agora
            # ela fica só armada, esperando o primeiro clique de
            # verdade dentro da viewport (o modal() abaixo trata isso
            # igual trata o início de qualquer mecha seguinte).
            self.points = []
            self.raw_coords = []
            self.anchored = False
            self.in_stroke = False

        context.window_manager.modal_handler_add(self)
        self._update_status_text(context)
        return {'RUNNING_MODAL'}

    def _start_stroke(self, context, event):
        """Reseta o estado de UM traço (não da sessão inteira) e tenta
        registrar o primeiro ponto a partir do evento que o iniciou."""
        self.points = []
        self.raw_coords = []
        self.anchored = False
        self.in_stroke = True

        started_in_viewport = (
            context.area is not None and context.area.type == 'VIEW_3D'
            and context.region is not None and context.region.type == 'WINDOW'
        )
        if started_in_viewport:
            self._add_point(context, event)

    def _draw_callback(self):
        draw_stroke_preview(self.points)

    def _remove_draw_handler(self):
        if getattr(self, "_draw_handler", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handler, 'WINDOW')
            self._draw_handler = None

    def _update_status_text(self, context):
        if context.scene.hair_draw_mode == 'TWO_POINT':
            base = (
                "Clique na cabeça pra ancorar e começar a mecha. Depois, "
                "mova o mouse pra traçar; clique ou Enter termina."
            )
        else:
            base = (
                "Clique na cabeça pra ancorar e arraste pra traçar (pode "
                "sair da superfície e formar um cacho solto). Solte o "
                "botão pra confirmar."
            )
        context.workspace.status_text_set(
            base + " Repita pra desenhar outra mecha. Ctrl+Z desfaz a "
            "última mecha. Space encerra a sessão."
        )

    def modal(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            return {'PASS_THROUGH'}
        if context.region is None or context.region.type != 'WINDOW':
            return {'PASS_THROUGH'}

        context.area.tag_redraw()

        two_point_mode = context.scene.hair_draw_mode == 'TWO_POINT'

        if event.type == 'MOUSEMOVE' and self.in_stroke:
            self._add_point(context, event)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                if not self.in_stroke:
                    # não tem traço rolando: este clique começa uma mecha nova
                    self._start_stroke(context, event)
                    return {'RUNNING_MODAL'}
                elif two_point_mode:
                    # modo Contínuo: segundo clique termina o traço atual
                    self._end_stroke(context)
                    return {'RUNNING_MODAL'}
            elif event.value == 'RELEASE' and self.in_stroke and not two_point_mode:
                # modo Livre: soltar o botão termina o traço atual
                self._end_stroke(context)
                return {'RUNNING_MODAL'}

        elif two_point_mode and event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS' and self.in_stroke:
            self._end_stroke(context)
            return {'RUNNING_MODAL'}

        elif event.type in {'RIGHTMOUSE', 'ESC'} and self.in_stroke:
            # cancela só o traço em andamento, sem sair da sessão
            self.in_stroke = False
            self.points = []
            return {'RUNNING_MODAL'}

        elif event.type == 'Z' and event.ctrl and event.value == 'PRESS' and not self.in_stroke:
            self._undo_last_stroke(context)
            return {'RUNNING_MODAL'}

        elif event.type == 'SPACE' and event.value == 'PRESS' and not self.in_stroke:
            self._end_session(context)
            return {'FINISHED'}

        elif event.type == 'ESC' and not self.in_stroke:
            # fora de um traço, Esc também encerra a sessão (Space é o principal)
            self._end_session(context)
            return {'FINISHED'}

        elif event.type in self.NAV_PASSTHROUGH:
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}

    def _end_stroke(self, context):
        """Termina o traço atual (RELEASE no modo Livre, segundo clique/
        Enter no modo Contínuo). Confirma a mecha se ancorada e com
        pontos suficientes; senão descarta silenciosamente (clique no
        vazio) ou avisa (traço curto demais). A sessão continua rodando
        de qualquer forma, pronta pro próximo traço. Importante: limpa
        self.points em TODOS os casos — senão o preview em laranja
        continua desenhando a última mecha na tela até o próximo traço
        de fato começar, dando a impressão de uma linha "fantasma"
        aparecendo antes de qualquer clique novo."""
        try:
            if not self.anchored:
                return

            if len(self.points) < 2:
                self.report({'WARNING'}, "Mecha muito curta, ignorada")
                return

            self._commit_stroke(context)
            self.strand_count += 1
        finally:
            self.in_stroke = False
            self.points = []
            self.raw_coords = []

    def _end_session(self, context):
        """Encerra a sessão de desenho inteira: solta o preview, limpa
        a status bar, e volta pra ferramenta de Seleção."""
        self._remove_draw_handler()
        context.workspace.status_text_set(None)
        self.report({'INFO'}, f"{self.strand_count} mecha(s) criada(s)")
        try:
            bpy.ops.wm.tool_set_by_id(name="builtin.select_box")
        except RuntimeError:
            pass

    def _undo_last_stroke(self, context):
        """Desfaz a última mecha confirmada nesta sessão. Como a sessão
        inteira é UMA operação modal (só registra undo do Blender ao
        terminar com Space/Esc), o Ctrl+Z nativo não desfaz mecha por
        mecha durante a sessão — por isso esse controle manual."""
        if not self.spline_history:
            self.report({'INFO'}, "Nada para desfazer")
            return

        curve_obj, spline = self.spline_history.pop()
        self.strand_count -= 1

        was_edit = context.mode == 'EDIT_CURVE'
        if was_edit:
            bpy.ops.object.mode_set(mode='OBJECT')

        curve_obj.data.splines.remove(spline)

        if len(curve_obj.data.splines) == 0:
            data = curve_obj.data
            bpy.data.objects.remove(curve_obj, do_unlink=True)
            bpy.data.curves.remove(data)
            if self.curve_obj is curve_obj:
                self.curve_obj = None
        elif was_edit:
            bpy.ops.object.mode_set(mode='EDIT')

        self.report({'INFO'}, "Última mecha desfeita")

    def _get_raycast_targets(self, context):
        targets = [self.target]
        if context.scene.hair_overlap_hair:
            targets.extend(collect_existing_hair_objects(exclude=self.curve_obj))
        return targets

    def _add_point(self, context, event):
        raw_coord = (event.mouse_region_x, event.mouse_region_y)

        self.raw_coords.append(raw_coord)
        if len(self.raw_coords) > STABILIZER_MAX_WINDOW:
            self.raw_coords = self.raw_coords[-STABILIZER_MAX_WINDOW:]

        coord = self._stabilized_coord(context)
        targets = self._get_raycast_targets(context)

        if not self.anchored:
            hit = raycast_targets(context, coord, targets)
            if hit is None:
                return
            self.anchored = True
            self.points.append(hit)
            return

        last = self.points[-1] if self.points else None
        p = sample_point(context, coord, targets, last)
        if p is None:
            return
        if not self.points or (p - self.points[-1]).length > 0.002:
            self.points.append(p)

    def _stabilized_coord(self, context):
        window = max(1, min(context.scene.hair_stroke_stabilizer, len(self.raw_coords)))
        recent = self.raw_coords[-window:]
        avg_x = sum(c[0] for c in recent) / len(recent)
        avg_y = sum(c[1] for c in recent) / len(recent)
        return (avg_x, avg_y)

    def _commit_stroke(self, context):
        was_edit = context.mode == 'EDIT_CURVE'
        if was_edit:
            bpy.ops.object.mode_set(mode='OBJECT')

        if self.curve_obj is None:
            curve_data = bpy.data.curves.new(HAIR_STRAND_PREFIX, type='CURVE')
            curve_data.dimensions = '3D'
            curve_data.bevel_mode = 'OBJECT'
            curve_data.bevel_object = resolve_bevel_object(context)
            curve_data.use_fill_caps = True

            self.curve_obj = bpy.data.objects.new(HAIR_STRAND_PREFIX, curve_data)
            resolve_safe_collection(context).objects.link(self.curve_obj)

        ensure_object_in_view_layer(context, self.curve_obj)

        for other in context.selected_objects:
            if other is not self.curve_obj:
                other.select_set(False)
        context.view_layer.objects.active = self.curve_obj
        self.curve_obj.select_set(True)

        scene = context.scene

        if len(self.points) > 2 and scene.hair_stroke_simplify > 0.0:
            self.points = simplify_stroke_points(self.points, scene.hair_stroke_simplify)

        spline = add_spline_from_points(self.curve_obj, self.points)

        if scene.hair_taper_mode != 'OFF':
            apply_taper_to_spline(
                spline, scene.hair_taper_fraction, scene.hair_taper_tip_radius,
                scene.hair_taper_mode
            )

        self.spline_history.append((self.curve_obj, spline))

        if was_edit:
            bpy.ops.object.mode_set(mode='EDIT')


class HAIR_OT_toggle_snap(bpy.types.Operator):
    bl_idname = "hair.toggle_snap"
    bl_label = "Alternar Snap"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ts = context.scene.tool_settings
        currently_face_snap = False
        if hasattr(ts, "snap_elements"):
            currently_face_snap = ts.use_snap and ts.snap_elements == {'FACE'}
        elif hasattr(ts, "snap_elements_base"):
            currently_face_snap = ts.use_snap and ts.snap_elements_base == {'FACE'}

        if currently_face_snap:
            ts.use_snap = False
        else:
            enable_surface_snap(context)
        return {'FINISHED'}


class HAIR_OT_normalize_custom_profile(bpy.types.Operator):
    bl_idname = "hair.normalize_custom_profile"
    bl_label = "Renormalizar Escala"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        custom = context.scene.hair_profile_custom
        if custom is None:
            self.report({'ERROR'}, "Escolha um objeto de curva em 'Perfil Customizado'")
            return {'CANCELLED'}

        normalize_custom_profile_scale(custom, context.scene.hair_thickness_scale, force=True)
        return {'FINISHED'}


class HAIR_OT_apply_profile(bpy.types.Operator):
    bl_idname = "hair.apply_profile"
    bl_label = "Aplicar Perfil"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            self.report({'ERROR'}, "Selecione uma curva de cabelo")
            return {'CANCELLED'}

        kind = context.scene.hair_profile_kind
        if kind == 'CUSTOM' and context.scene.hair_profile_custom is None:
            self.report({'ERROR'}, "Escolha um objeto de curva em 'Perfil Customizado'")
            return {'CANCELLED'}

        obj.data.bevel_mode = 'OBJECT'
        obj.data.bevel_object = resolve_bevel_object(context)

        return {'FINISHED'}


class HAIR_OT_apply_taper(bpy.types.Operator):
    bl_idname = "hair.apply_taper"
    bl_label = "Aplicar Afinamento"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE':
            self.report({'ERROR'}, "Selecione uma curva de cabelo")
            return {'CANCELLED'}

        scene = context.scene
        for spline in obj.data.splines:
            apply_taper_to_spline(
                spline, scene.hair_taper_fraction, scene.hair_taper_tip_radius,
                scene.hair_taper_mode
            )

        return {'FINISHED'}


class HAIR_OT_set_thickness(bpy.types.Operator):
    bl_idname = "hair.set_thickness"
    bl_label = "Ajustar Espessura"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVE' or obj.data.bevel_object is None:
            self.report({'ERROR'}, "Curva ativa não tem perfil aplicado")
            return {'CANCELLED'}

        apply_profile_scale(obj.data.bevel_object, context.scene.hair_thickness_scale)
        return {'FINISHED'}


class HAIR_WT_draw_tool(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'
    bl_idname = "hair.draw_tool"
    bl_label = "Cabelo"
    bl_description = (
        "Desenha mechas de cabelo grudadas na superfície escolhida.\n"
        "Clique (e arraste, no modo Livre) pra desenhar; navegue\n"
        "livremente entre uma mecha e outra"
    )
    bl_icon = "ops.curve.draw"
    bl_widget = None
    bl_keymap = (
        ("hair.draw_strand", {"type": 'LEFTMOUSE', "value": 'PRESS'}, None),
        ("wm.tool_set_by_id", {"type": 'SPACE', "value": 'PRESS'},
         {"properties": [("name", "builtin.select_box")]}),
    )

    def draw_settings(context, layout, tool):
        scene = context.scene
        layout.prop(scene, "hair_surface_target", text="Cabeça")
        layout.prop(scene, "hair_draw_mode", text="")
        layout.prop(scene, "hair_stroke_stabilizer", text="Estabilização", slider=True)


class HAIR_PT_panel(bpy.types.Panel):
    bl_label = "Hair"
    bl_idname = "HAIR_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Hair"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        col = layout.column(align=True)
        col.prop(scene, "hair_surface_target", text="Cabeça (superfície)")

        layout.separator()
        col = layout.column(align=True)
        col.prop(scene, "hair_draw_mode", text="Modo")
        col.prop(scene, "hair_stroke_stabilizer", text="Estabilização", slider=True)
        col.prop(scene, "hair_stroke_simplify", text="Simplificar (reduz polígonos)")
        col.operator("hair.draw_strand", text="Desenhar Mecha (1 traço)", icon='CURVE_DATA')
        col.operator("hair.toggle_snap", icon='SNAP_FACE', text="Snap p/ edição manual")
        col.prop(scene, "hair_overlap_hair")

        layout.separator()
        taper_box = layout.box()
        taper_box.prop(scene, "hair_taper_mode", text="Afinar")
        if scene.hair_taper_mode != 'OFF':
            taper_box.prop(scene, "hair_taper_fraction")
            taper_box.prop(scene, "hair_taper_tip_radius", text="Espessura na ponta afinada")
        taper_box.operator("hair.apply_taper", text="Aplicar à curva ativa")

        layout.separator()
        box = layout.box()
        box.label(text="Estilização (perfil)")
        box.prop(scene, "hair_profile_kind", text="")
        if scene.hair_profile_kind == 'CUSTOM':
            row = box.row(align=True)
            row.prop(scene, "hair_profile_custom", text="Curva")
            row.operator("hair.normalize_custom_profile", text="", icon='FILE_REFRESH')
        elif scene.hair_profile_kind == 'ROUND':
            box.prop(scene, "hair_profile_segments", text="Lados (segmentos)")
            box.prop(scene, "hair_profile_smooth", text="Suavizar perfil")
        elif scene.hair_profile_kind == 'STAR':
            box.prop(scene, "hair_profile_smooth", text="Suavizar perfil")
        box.operator("hair.apply_profile", text="Aplicar à curva ativa")

        layout.separator()
        row = layout.row(align=True)
        row.prop(scene, "hair_thickness_scale", text="Espessura")
        row.operator("hair.set_thickness", text="", icon='FILE_REFRESH')

        layout.separator()
        info = layout.box()
        info.label(text="Fluxo:")
        info.label(text="  1. Escolha a cabeça acima")
        info.label(text="  2. Selecione a ferramenta 'Cabelo' na")
        info.label(text="     caixa de ferramentas do Viewport (T)")
        info.label(text="  3. Clique NA CABEÇA pra ancorar e")
        info.label(text="     começar a mecha (clicar no vazio ou")
        info.label(text="     em outro objeto não faz nada). Depois")
        info.label(text="     de ancorada ela pode sair da")
        info.label(text="     superfície e formar um cacho solto.")
        info.label(text="  4. Solte o botão (ou clique/Enter no")
        info.label(text="     modo Contínuo) pra confirmar — e")
        info.label(text="     repita pra desenhar outra mecha.")
        info.label(text="  5. Ctrl+Z desfaz a última mecha. Space")
        info.label(text="     encerra a sessão de vez.")


classes = (
    HAIR_OT_draw_strand,
    HAIR_OT_toggle_snap,
    HAIR_OT_apply_profile,
    HAIR_OT_normalize_custom_profile,
    HAIR_OT_apply_taper,
    HAIR_OT_set_thickness,
    HAIR_PT_panel,
)

PROFILE_ITEMS = [
    ('ROUND', "Redondo", "Fio cilíndrico clássico"),
    ('FLAT', "Fita (Flat)", "Fita achatada, tipo hair card"),
    ('SQUARE', "Quadrado", "Seção quadrada"),
    ('STAR', "Estrela", "Seção estilizada em estrela"),
    ('CUSTOM', "Customizado", "Use qualquer curva 2D como perfil"),
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.hair_surface_target = bpy.props.PointerProperty(
        name="Superfície", type=bpy.types.Object,
        description="Mesh da cabeça onde as mechas serão desenhadas/grudadas",
        poll=lambda self, obj: obj.type == 'MESH'
    )

    bpy.types.Scene.hair_profile_kind = bpy.props.EnumProperty(
        name="Perfil", items=PROFILE_ITEMS, default='ROUND'
    )
    bpy.types.Scene.hair_profile_custom = bpy.props.PointerProperty(
        name="Perfil Customizado", type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'CURVE'
    )
    bpy.types.Scene.hair_profile_segments = bpy.props.IntProperty(
        name="Lados do perfil", default=8, min=3, max=32,
        description="teste"
    )
    bpy.types.Scene.hair_profile_smooth = bpy.props.BoolProperty(
        name="Suavizar perfil", default=True,
        description="teste"
    )
    bpy.types.Scene.hair_thickness_scale = bpy.props.FloatProperty(
        name="Espessura", default=1.0, min=0.01, max=10.0
    )

    bpy.types.Scene.hair_active_curve = bpy.props.PointerProperty(
        name="Mecha Ativa", type=bpy.types.Object,
        description="teste",
        poll=lambda self, obj: obj.type == 'CURVE' and obj.name.startswith(HAIR_STRAND_PREFIX)
    )

    bpy.types.Scene.hair_overlap_hair = bpy.props.BoolProperty(
        name="Sobrepor em cabelo já desenhado", default=False,
        description="teste"
    )
    bpy.types.Scene.hair_draw_mode = bpy.props.EnumProperty(
        name="Modo de desenho", default='FREE',
        items=[
            ('FREE', "Livre (arrastar)", "Clique e arraste continuamente pra desenhar a mecha; solte pra confirmar"),
            ('TWO_POINT', "Contínuo (clique p/ começar/parar)", "teste"),
        ],
        description="Como cada mecha é desenhada"
    )

    bpy.types.Scene.hair_stroke_stabilizer = bpy.props.IntProperty(
        name="Estabilização", default=0, min=0, max=STABILIZER_MAX_WINDOW,
        description="teste"
    )

    bpy.types.Scene.hair_stroke_simplify = bpy.props.FloatProperty(
        name="Simplificar Traço", default=0.0008, min=0.0, max=0.02,
        subtype='DISTANCE',
        description="teste"
    )

    bpy.types.Scene.hair_taper_mode = bpy.props.EnumProperty(
        name="Afinar", default='OFF',
        items=[
            ('OFF', "Desligado", "Espessura uniforme (bom pra dreads/mechas grossas)"),
            ('TIP', "Só na ponta final", "Afina só o final do traço"),
            ('ROOT', "Só na raiz", "Afina só o início do traço"),
            ('BOTH', "Nas duas pontas", "Afina início e fim do traço"),
        ],
        description="teste"
    )
    bpy.types.Scene.hair_taper_fraction = bpy.props.FloatProperty(
        name="Trecho afinado", default=0.35, min=0.05, max=1.0,
        subtype='FACTOR',
        description="teste"
    )
    bpy.types.Scene.hair_taper_tip_radius = bpy.props.FloatProperty(
        name="Espessura na ponta", default=0.05, min=0.0, max=1.0,
        subtype='FACTOR',
        description="teste"
    )

    bpy.utils.register_tool(HAIR_WT_draw_tool, after={"builtin.cursor"}, separator=True, group=False)


def unregister():
    bpy.utils.unregister_tool(HAIR_WT_draw_tool)

    del bpy.types.Scene.hair_surface_target
    del bpy.types.Scene.hair_thickness_scale
    del bpy.types.Scene.hair_profile_custom
    del bpy.types.Scene.hair_profile_kind
    del bpy.types.Scene.hair_profile_segments
    del bpy.types.Scene.hair_profile_smooth
    del bpy.types.Scene.hair_active_curve
    del bpy.types.Scene.hair_overlap_hair
    del bpy.types.Scene.hair_draw_mode
    del bpy.types.Scene.hair_stroke_stabilizer
    del bpy.types.Scene.hair_stroke_simplify
    del bpy.types.Scene.hair_taper_mode
    del bpy.types.Scene.hair_taper_fraction
    del bpy.types.Scene.hair_taper_tip_radius

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
