import bpy
import math
import gpu
from collections import deque
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from bpy_extras import view3d_utils

from .core import (
    HAIR_MECHA_PREFIX,
    HAIR_GROWTH_PREFIX,
    TARGET_PROFILE_RADIUS,
    COMB_UNDO_STEPS,
    apply_curve_style,
    apply_profile_scale,
    _active_curve_object,
    _snap_active_curve_root_to_surface,
    _ensure_custom_profile_proxy,
    _select_only,
    _ensure_object_mode,
    _enter_edit_mode,
    ensure_object_in_view_layer,
    ensure_growth_vertex_group,
    get_selected_growth_vertex_group_name,
    set_active_vertex_group,
    _create_growth_from_paint,
    _is_hair_curve_object,
    _style_scope_targets,
    _auto_apply_style,
    _apply_guide_to_targets,
    _embedded_root_point,
    _object_up_reference,
    _build_mecha_points,
    _new_mecha_object_at,
    _remove_last_spline_from_curve_object,
    raycast_targets,
)


# ---------------------------------------------------------------------------
# Operadores simples
# ---------------------------------------------------------------------------


class HAIR_OT_snap_active_mecha(bpy.types.Operator):
    bl_idname = "hair.snap_active_mecha"
    bl_label = "Snap da Mecha Ativa"
    bl_description = "Reposiciona a mecha ativa para que a raiz fique sobre a superfície escolhida"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = _active_curve_object(context)
        if obj is None:
            self.report({'ERROR'}, "Selecione uma curva de cabelo ativa")
            return {'CANCELLED'}

        ok, error = _snap_active_curve_root_to_surface(context, obj)
        if not ok:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}

        self.report({'INFO'}, "Raiz ajustada na superfície")
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

        proxy = _ensure_custom_profile_proxy(context, custom)
        if proxy is None:
            self.report({'ERROR'}, "Não foi possível criar o proxy do perfil customizado")
            return {'CANCELLED'}

        self.report({'INFO'}, "Perfil customizado atualizado")
        return {'FINISHED'}


class HAIR_OT_apply_profile(bpy.types.Operator):
    bl_idname = "hair.apply_profile"
    bl_label = "Aplicar Perfil"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = _active_curve_object(context)
        if obj is None:
            self.report({'ERROR'}, "Selecione uma curva de cabelo")
            return {'CANCELLED'}

        apply_curve_style(obj, context)
        self.report({'INFO'}, "Perfil aplicado")
        return {'FINISHED'}


class HAIR_OT_set_thickness(bpy.types.Operator):
    bl_idname = "hair.set_thickness"
    bl_label = "Ajustar Espessura"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = _active_curve_object(context)
        if obj is None:
            self.report({'ERROR'}, "Selecione uma curva de cabelo")
            return {'CANCELLED'}

        apply_curve_style(obj, context)
        if obj.data.bevel_object is None:
            self.report({'ERROR'}, "Não foi possível aplicar um perfil de espessura")
            return {'CANCELLED'}

        apply_profile_scale(obj.data.bevel_object, context.scene.hair_thickness_scale)
        self.report({'INFO'}, "Espessura atualizada")
        return {'FINISHED'}


class HAIR_OT_reset_local_thickness(bpy.types.Operator):
    bl_idname = "hair.reset_local_thickness"
    bl_label = "Usar Espessura Global"
    bl_description = "Remove a espessura individual desta mecha (definida com a tecla S) e volta a usar o valor global do painel"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = _active_curve_object(context)
        if obj is None:
            self.report({'ERROR'}, "Selecione uma curva de cabelo")
            return {'CANCELLED'}

        if "hair_thickness_local_scale" in obj:
            del obj["hair_thickness_local_scale"]

        apply_curve_style(obj, context)
        bevel_obj = obj.data.bevel_object
        if bevel_obj is not None:
            apply_profile_scale(bevel_obj, context.scene.hair_thickness_scale)

        self.report({'INFO'}, "Espessura local removida, usando valor global")
        return {'FINISHED'}


class HAIR_OT_apply_style_now(bpy.types.Operator):
    bl_idname = "hair.apply_style_now"
    bl_label = "Aplicar Agora"
    bl_description = "Força a aplicação do perfil/espessura/afinação/tampas no escopo escolhido (útil após mexer em parâmetros de forma do perfil, como curvatura ou nº de fios do tufo)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = _style_scope_targets(context)
        if not targets:
            self.report({'ERROR'}, "Nenhuma mecha encontrada no escopo escolhido")
            return {'CANCELLED'}

        _auto_apply_style(context)
        self.report({'INFO'}, f"Estilo aplicado a {len(targets)} mecha(s)")
        return {'FINISHED'}


class HAIR_OT_apply_guide_now(bpy.types.Operator):
    bl_idname = "hair.apply_guide_now"
    bl_label = "Aplicar Guia Agora"
    bl_description = (
        "Reconstrói a forma das mechas (no escopo escolhido acima) usando os valores "
        "atuais de Comprimento/Elevação/Ângulo/Curvatura/Afinar ponta, mantendo cada "
        "raiz no lugar onde foi criada. Use isto se 'Atualizar ao vivo' estiver desligado"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = _style_scope_targets(context)
        if not targets:
            self.report({'ERROR'}, "Nenhuma mecha encontrada no escopo escolhido")
            return {'CANCELLED'}

        total = _apply_guide_to_targets(context, targets)
        if total == 0:
            self.report(
                {'WARNING'},
                "Nenhum fio tinha dados de guia salvos (mechas criadas em versões antigas do addon)",
            )
            return {'CANCELLED'}

        self.report({'INFO'}, f"Guia reaplicada em {total} fio(s)")
        return {'FINISHED'}


class HAIR_OT_convert_active_to_light_mesh(bpy.types.Operator):
    bl_idname = "hair.convert_active_to_light_mesh"
    bl_label = "Converter para Mesh Leve"
    bl_description = "Converte a curva ativa em mesh e aplica redução de polígonos"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = _active_curve_object(context)
        if obj is None:
            self.report({'ERROR'}, "Selecione uma curva de cabelo")
            return {'CANCELLED'}

        scene = context.scene
        reduction_ratio = scene.hair_mesh_reduction_ratio

        was_edit = context.mode == 'EDIT_CURVE'
        if was_edit:
            _ensure_object_mode()

        _select_only(context, obj)

        try:
            bpy.ops.object.convert(target='MESH')
        except RuntimeError:
            self.report({'ERROR'}, "Falha ao converter a curva em mesh")
            if was_edit:
                _enter_edit_mode()
            return {'CANCELLED'}

        mesh_obj = context.active_object
        if mesh_obj is None or mesh_obj.type != 'MESH':
            self.report({'ERROR'}, "Falha ao converter a curva em mesh")
            if was_edit:
                _enter_edit_mode()
            return {'CANCELLED'}

        if reduction_ratio < 0.999:
            mod = mesh_obj.modifiers.new(name="HairDecimate", type='DECIMATE')
            mod.decimate_type = 'COLLAPSE'
            mod.ratio = reduction_ratio
            try:
                bpy.ops.object.modifier_apply(modifier=mod.name)
            except RuntimeError:
                self.report({'WARNING'}, "Mesh criada, mas não foi possível aplicar o Decimate")

        self.report({'INFO'}, f"Mesh criada com preservação de {int(reduction_ratio * 100)}%")
        if was_edit:
            _enter_edit_mode()
        return {'FINISHED'}


class HAIR_OT_open_weight_paint(bpy.types.Operator):
    bl_idname = "hair.open_weight_paint"
    bl_label = "Editar Vertex Group"
    bl_description = "Abre a superfície escolhida em Weight Paint com o vertex group selecionado"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        target = scene.hair_surface_target
        if target is None:
            self.report({'ERROR'}, "Escolha a superfície primeiro")
            return {'CANCELLED'}
        if target.type != 'MESH':
            self.report({'ERROR'}, "A superfície precisa ser uma malha")
            return {'CANCELLED'}

        ensure_object_in_view_layer(context, target)
        group_name = get_selected_growth_vertex_group_name(scene)
        vg = target.vertex_groups.get(group_name)
        if vg is None:
            vg = ensure_growth_vertex_group(target, group_name)

        _ensure_object_mode()
        _select_only(context, target)
        set_active_vertex_group(target, vg.name)

        try:
            bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
        except RuntimeError:
            self.report({'ERROR'}, "Não foi possível abrir o Weight Paint")
            return {'CANCELLED'}

        self.report({'INFO'}, "Weight Paint aberto")
        return {'FINISHED'}


class HAIR_OT_create_vertex_group(bpy.types.Operator):
    bl_idname = "hair.create_vertex_group"
    bl_label = "Criar Vertex Group"
    bl_description = "Cria um novo vertex group na cabeça e o deixa selecionado"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        target = scene.hair_surface_target
        if target is None:
            self.report({'ERROR'}, "Escolha a superfície primeiro")
            return {'CANCELLED'}
        if target.type != 'MESH':
            self.report({'ERROR'}, "A superfície precisa ser uma malha")
            return {'CANCELLED'}

        group_name = (scene.hair_new_vertex_group_name or "").strip()
        if not group_name:
            self.report({'ERROR'}, "Digite um nome para o novo vertex group")
            return {'CANCELLED'}

        ensure_object_in_view_layer(context, target)
        vg = ensure_growth_vertex_group(target, group_name)
        scene.hair_growth_vertex_group = vg.name
        set_active_vertex_group(target, vg.name)

        self.report({'INFO'}, f"Vertex group '{vg.name}' criado")
        return {'FINISHED'}


class HAIR_OT_apply_growth_from_paint(bpy.types.Operator):
    bl_idname = "hair.apply_growth_from_paint"
    bl_label = "Aplicar Crescimento"
    bl_description = "Gera ou recria o cabelo a partir do vertex group pintado"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj, error = _create_growth_from_paint(context)
        if error is not None:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}

        self.report({'INFO'}, "Crescimento aplicado a partir da pintura")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Escova de pentear (brush interativo)
# ---------------------------------------------------------------------------


def _comb_gather_targets(context):
    selected = [
        o for o in context.selected_objects
        if o.type == 'CURVE' and (o.name.startswith(HAIR_MECHA_PREFIX) or o.name.startswith(HAIR_GROWTH_PREFIX))
    ]
    if selected:
        return selected

    found = []
    for o in context.scene.objects:
        if o.type != 'CURVE':
            continue
        if not (o.name.startswith(HAIR_MECHA_PREFIX) or o.name.startswith(HAIR_GROWTH_PREFIX)):
            continue
        if not o.visible_get():
            continue
        found.append(o)
    return found


def _comb_smoothstep_falloff(dist, radius):
    if radius <= 1e-6:
        return 0.0
    t = 1.0 - (dist / radius)
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * (3.0 - 2.0 * t)


def _draw_comb_cursor_callback(op, context):
    if op.mouse is None:
        return

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')

    if op.resizing and op.resize_anchor is not None:
        cx, cy = op.resize_anchor
        radius = max(2.0, op.radius)
        segments = 48
        coords = []
        for i in range(segments + 1):
            a = (2.0 * math.pi * i) / segments
            coords.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))

        color = (0.95, 0.85, 0.15, 0.9)
        gpu.state.line_width_set(2.0)
        batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": coords})
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)

        guide_batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": [(cx, cy), tuple(op.mouse)]})
        shader.uniform_float("color", (0.95, 0.85, 0.15, 0.5))
        guide_batch.draw(shader)

        anchor_batch = batch_for_shader(shader, 'POINTS', {"pos": [(cx, cy)]})
        gpu.state.point_size_set(5.0)
        shader.uniform_float("color", color)
        anchor_batch.draw(shader)

        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')
        return

    mx, my = op.mouse
    radius = max(2.0, op.radius)
    segments = 48
    coords = []
    for i in range(segments + 1):
        a = (2.0 * math.pi * i) / segments
        coords.append((mx + radius * math.cos(a), my + radius * math.sin(a)))

    if op.smoothing:
        color = (0.30, 0.65, 1.0, 0.9)
    elif op.dragging:
        color = (1.0, 0.55, 0.15, 0.9)
    else:
        color = (1.0, 1.0, 1.0, 0.55)

    gpu.state.line_width_set(2.0)
    batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": coords})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)

    center_batch = batch_for_shader(shader, 'POINTS', {"pos": [(mx, my)]})
    gpu.state.point_size_set(4.0)
    shader.uniform_float("color", color)
    center_batch.draw(shader)

    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def _draw_thickness_preview(op, context):
    if not getattr(op, "thickness_adjusting", False):
        return

    root = getattr(op, "thickness_preview_root", None)
    if root is None:
        return

    rv3d = context.region_data
    if rv3d is None:
        return

    scale = max(0.05, min(10.0, op.thickness_preview_scale))
    radius_world = TARGET_PROFILE_RADIUS * scale

    view_right = rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
    view_up = rv3d.view_rotation @ Vector((0.0, 1.0, 0.0))

    center = root
    segments = 48
    coords = []
    for i in range(segments + 1):
        a = (2.0 * math.pi * i) / segments
        offset = (view_right * math.cos(a) + view_up * math.sin(a)) * radius_world
        coords.append(tuple(center + offset))

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.line_width_set(2.5)

    batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": coords})
    shader.bind()
    shader.uniform_float("color", (0.75, 0.35, 1.0, 0.9))
    batch.draw(shader)

    center_batch = batch_for_shader(shader, 'POINTS', {"pos": [tuple(center)]})
    gpu.state.point_size_set(6.0)
    shader.uniform_float("color", (0.95, 0.75, 1.0, 0.95))
    center_batch.draw(shader)

    gpu.state.point_size_set(1.0)
    gpu.state.line_width_set(1.0)
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.blend_set('NONE')


class HAIR_OT_comb_brush(bpy.types.Operator):
    bl_idname = "hair.comb_brush"
    bl_label = "Pentear (Escova)"
    bl_description = (
        "Escova interativa: arraste com o botão esquerdo para pentear as mechas. "
        "Ctrl+arraste para alisar. Aperte F e mova o mouse para ajustar o raio "
        "(clique, Enter ou F de novo confirma; Esc cancela o ajuste). "
        "Ctrl+Z desfaz o último traço sem sair da escova. Enter confirma, Esc cancela"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        if context.area.type != 'VIEW_3D':
            self.report({'ERROR'}, "Use esta ferramenta dentro da viewport 3D")
            return {'CANCELLED'}

        self.targets = _comb_gather_targets(context)
        if not self.targets:
            self.report(
                {'ERROR'},
                "Nenhuma mecha encontrada. Selecione as curvas de cabelo ou deixe-as visíveis na cena",
            )
            return {'CANCELLED'}

        scene = context.scene
        self.radius = float(scene.hair_comb_radius)
        self.strength = float(scene.hair_comb_strength)
        self.pin_root = bool(scene.hair_comb_pin_root)

        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.prev_mouse = self.mouse.copy()
        self.dragging = False
        self.smoothing = False
        self._handle = None

        self.resizing = False
        self.resize_anchor = None
        self.resize_original_radius = self.radius

        self._stroke_undo_stack = deque(maxlen=COMB_UNDO_STEPS)
        self._stroke_snapshot = None
        self._stroke_changed = False

        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_comb_cursor_callback, (self, context), 'WINDOW', 'POST_PIXEL'
        )

        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _snapshot_targets(self):
        snapshot = {}
        for obj in self.targets:
            if obj is None or obj.name not in bpy.data.objects:
                continue
            per_object = []
            for spline_index, spline in enumerate(obj.data.splines):
                if spline.type != 'BEZIER':
                    continue
                coords = [bp.co.copy() for bp in spline.bezier_points]
                per_object.append((spline_index, coords))
            if per_object:
                snapshot[obj.name] = per_object
        return snapshot

    def _restore_snapshot(self, snapshot):
        for obj_name, per_object in snapshot.items():
            obj = bpy.data.objects.get(obj_name)
            if obj is None:
                continue
            for spline_index, coords in per_object:
                if spline_index >= len(obj.data.splines):
                    continue
                spline = obj.data.splines[spline_index]
                if spline.type != 'BEZIER':
                    continue
                for bp, co in zip(spline.bezier_points, coords):
                    bp.co = co
            obj.data.update_tag()

    def _undo_last_stroke(self, context):
        if not self._stroke_undo_stack:
            self.report({'INFO'}, "Nada para desfazer na escova")
            return
        snapshot = self._stroke_undo_stack.pop()
        self._restore_snapshot(snapshot)
        context.view_layer.update()
        context.area.tag_redraw()
        self.report({'INFO'}, "Última pincelada desfeita")

    def _update_resize_radius(self, context):
        if self.resize_anchor is None:
            return
        distance = (self.mouse - self.resize_anchor).length
        self.radius = max(5.0, min(500.0, distance))
        context.scene.hair_comb_radius = self.radius

    def modal(self, context, event):
        context.area.tag_redraw()

        if event.type == 'MOUSEMOVE':
            self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
            if self.resizing:
                self._update_resize_radius(context)
            elif self.dragging or self.smoothing:
                self._apply_brush(context)
            self.prev_mouse = self.mouse.copy()
            return {'RUNNING_MODAL'}

        if event.type == 'F' and event.value == 'PRESS':
            if self.resizing:
                self.resizing = False
                self.resize_anchor = None
            else:
                self.resizing = True
                self.resize_anchor = self.mouse.copy()
                self.resize_original_radius = self.radius
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE':
            if self.resizing:
                if event.value == 'PRESS':
                    self.resizing = False
                    self.resize_anchor = None
                return {'RUNNING_MODAL'}

            if event.value == 'PRESS':
                self._stroke_snapshot = self._snapshot_targets()
                self._stroke_changed = False
                self.prev_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
                self.smoothing = event.ctrl
                self.dragging = not event.ctrl
                self._apply_brush(context)
            elif event.value == 'RELEASE':
                if self._stroke_changed and self._stroke_snapshot:
                    self._stroke_undo_stack.append(self._stroke_snapshot)
                self._stroke_snapshot = None
                self._stroke_changed = False
                self.dragging = False
                self.smoothing = False
            return {'RUNNING_MODAL'}

        if event.type == 'Z' and event.value == 'PRESS':
            if event.ctrl and not event.shift and not event.alt:
                self._undo_last_stroke(context)
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}

        if event.type in {
            'NUMPAD_1', 'NUMPAD_2', 'NUMPAD_3', 'NUMPAD_4', 'NUMPAD_5',
            'NUMPAD_6', 'NUMPAD_7', 'NUMPAD_8', 'NUMPAD_9', 'NUMPAD_PERIOD',
        }:
            return {'PASS_THROUGH'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            if self.resizing:
                self.radius = self.resize_original_radius
                context.scene.hair_comb_radius = self.radius
                self.resizing = False
                self.resize_anchor = None
                return {'RUNNING_MODAL'}
            self._finish(context)
            return {'CANCELLED'}

        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            if self.resizing:
                self.resizing = False
                self.resize_anchor = None
                return {'RUNNING_MODAL'}
            self._finish(context)
            return {'FINISHED'}

        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self._finish(context)

    def _finish(self, context):
        if self._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        context.area.tag_redraw()

    def _apply_brush(self, context):
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return

        for obj in self.targets:
            if obj is None or obj.name not in bpy.data.objects:
                continue

            matrix = obj.matrix_world
            matrix_inv = matrix.inverted()
            curve_data = obj.data
            obj_changed = False

            for spline in curve_data.splines:
                if spline.type != 'BEZIER':
                    continue
                points = spline.bezier_points
                n = len(points)
                if n < 2:
                    continue

                if self.dragging:
                    obj_changed = self._comb_drag_spline(points, n, matrix, matrix_inv, region, rv3d) or obj_changed
                elif self.smoothing:
                    obj_changed = self._comb_smooth_spline(points, n, matrix, matrix_inv, region, rv3d) or obj_changed

            if obj_changed:
                curve_data.update_tag()
                self._stroke_changed = True

        context.view_layer.update()

    def _comb_drag_spline(self, points, n, matrix, matrix_inv, region, rv3d):
        changed = False
        for i, bp in enumerate(points):
            if self.pin_root and i == 0:
                continue

            point_world = matrix @ bp.co
            screen = view3d_utils.location_3d_to_region_2d(region, rv3d, point_world)
            if screen is None:
                continue

            dist = (Vector(screen) - self.mouse).length
            if dist > self.radius:
                continue

            falloff = _comb_smoothstep_falloff(dist, self.radius)
            strand_weight = (i / (n - 1)) if self.pin_root else 1.0
            weight = falloff * strand_weight * self.strength
            if weight <= 0.0005:
                continue

            new_world = view3d_utils.region_2d_to_location_3d(region, rv3d, self.mouse, point_world)
            old_world = view3d_utils.region_2d_to_location_3d(region, rv3d, self.prev_mouse, point_world)
            if new_world is None or old_world is None:
                continue

            delta_world = new_world - old_world
            if delta_world.length < 1e-9:
                continue

            bp.co = matrix_inv @ (point_world + delta_world * weight)
            changed = True

        return changed

    def _comb_smooth_spline(self, points, n, matrix, matrix_inv, region, rv3d):
        if n < 3:
            return False

        originals = [bp.co.copy() for bp in points]
        changed = False
        start = 1 if self.pin_root else 0
        for i in range(start, n - 1):
            bp = points[i]
            point_world = matrix @ originals[i]
            screen = view3d_utils.location_3d_to_region_2d(region, rv3d, point_world)
            if screen is None:
                continue

            dist = (Vector(screen) - self.mouse).length
            if dist > self.radius:
                continue

            falloff = _comb_smoothstep_falloff(dist, self.radius)
            weight = falloff * self.strength * 0.5
            if weight <= 0.0005:
                continue

            target_local = (originals[i - 1] + originals[i + 1]) * 0.5
            bp.co = originals[i].lerp(target_local, weight)
            changed = True

        return changed


# ---------------------------------------------------------------------------
# Criar mecha por clique (brush de criação)
# ---------------------------------------------------------------------------


def _draw_mecha_brush_callback(op, context):
    if op.hit_point is None or op.hit_normal is None:
        return

    scene = context.scene
    embedded_root = _embedded_root_point(op.hit_point, op.hit_normal, scene.hair_root_embed_depth)
    up_reference = _object_up_reference(op.target)
    points = _build_mecha_points(
        embedded_root,
        op.hit_normal,
        op.length,
        op.lift,
        op.angle,
        curve_amount=op.curve_amount,
        up_reference=up_reference,
    )

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')

    color = (0.95, 0.85, 0.15, 0.9) if op.resizing else (0.30, 0.85, 1.0, 0.9)

    coords = [tuple(p) for p in points]
    gpu.state.line_width_set(3.0)
    batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": coords})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)

    root_batch = batch_for_shader(shader, 'POINTS', {"pos": [coords[0]]})
    gpu.state.point_size_set(7.0)
    shader.uniform_float("color", color)
    root_batch.draw(shader)

    if op.resizing and op.resize_anchor_world is not None:
        guide_coords = [tuple(op.resize_anchor_world), coords[0]]
        gpu.state.line_width_set(1.0)
        guide_batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": guide_coords})
        shader.uniform_float("color", (0.95, 0.85, 0.15, 0.5))
        guide_batch.draw(shader)

    if getattr(op, "thickness_adjusting", False):
        _draw_thickness_preview(op, context)

    gpu.state.point_size_set(1.0)
    gpu.state.line_width_set(1.0)
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.blend_set('NONE')


class HAIR_OT_create_mecha_brush(bpy.types.Operator):
    bl_idname = "hair.create_mecha_brush"
    bl_label = "Criar Mecha (Clique)"
    bl_description = (
        "Ferramenta interativa: clique na superfície para criar mechas onde o mouse "
        "estiver. Aperte F e mova o mouse para ajustar o comprimento em metros reais "
        "(clique, Enter ou F de novo confirma; Esc cancela o ajuste). "
        "Aperte S para ajustar a espessura desta mecha com preview (não afeta outras mechas). "
        "Clique esquerdo ou Enter confirma; Esc ou botão direito cancela. "
        "Ctrl+Z desfaz a última mecha criada sem sair da ferramenta. "
        "Enter, Esc ou clique direito sai da ferramenta"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        if context.area.type != 'VIEW_3D':
            self.report({'ERROR'}, "Use esta ferramenta dentro da viewport 3D")
            return {'CANCELLED'}

        scene = context.scene
        self.target = scene.hair_surface_target
        if self.target is None:
            self.report({'ERROR'}, "Escolha uma superfície primeiro")
            return {'CANCELLED'}

        self.length = max(0.001, float(scene.hair_guide_length))
        self.lift = float(scene.hair_guide_lift)
        self.angle = float(scene.hair_guide_angle)
        self.tip_taper = float(scene.hair_guide_tip_taper)
        self.curve_amount = float(scene.hair_guide_curve_amount)

        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.hit_point = None
        self.hit_normal = None
        self._handle = None

        self.resizing = False
        self.resize_anchor_2d = None
        self.resize_anchor_world = None
        self.resize_root_world = None
        self.resize_original_length = self.length

        self.thickness_adjusting = False
        self.thickness_anchor_mouse = None
        self.thickness_original_scale = scene.hair_thickness_scale
        self.thickness_preview_root = None
        self.thickness_preview_scale = scene.hair_thickness_scale
        # espessura local pendente: se o usuário aperta S antes de clicar pela
        # primeira vez, guardamos aqui e aplicamos assim que a mecha for criada
        self.pending_local_thickness = None

        self._created_stack = deque(maxlen=COMB_UNDO_STEPS)
        self._click_object_name = ""

        self._update_hit(context)

        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_mecha_brush_callback, (self, context), 'WINDOW', 'POST_VIEW'
        )

        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _update_hit(self, context):
        result = raycast_targets(context, self.mouse, [self.target])
        if result is None:
            self.hit_point = None
            self.hit_normal = None
            return
        world_hit, world_normal, _dist = result
        self.hit_point = world_hit
        self.hit_normal = world_normal

    def _update_resize_length(self, context):
        if self.resize_root_world is None or self.resize_anchor_2d is None:
            return

        region = context.region
        rv3d = context.region_data

        anchor_world = view3d_utils.region_2d_to_location_3d(
            region, rv3d, self.resize_anchor_2d, self.resize_root_world
        )
        current_world = view3d_utils.region_2d_to_location_3d(
            region, rv3d, self.mouse, self.resize_root_world
        )
        if anchor_world is None or current_world is None:
            return

        self.resize_anchor_world = anchor_world
        distance = (current_world - anchor_world).length
        self.length = max(0.001, distance)
        context.scene.hair_guide_length = self.length

    def _update_thickness_scale(self, context):
        if self.thickness_anchor_mouse is None:
            return

        delta = self.mouse - self.thickness_anchor_mouse
        delta_value = (delta.x + delta.y) * 0.01
        new_scale = self.thickness_original_scale * (1.0 + delta_value)
        new_scale = max(0.05, min(10.0, new_scale))
        self.thickness_preview_scale = new_scale

    def _confirm_thickness(self, context):
        """Aplica a espessura ajustada apenas na mecha atual (self._click_object_name),
        usando um proxy de perfil individual, sem tocar no objeto de perfil global
        nem em outras mechas da cena."""
        self.thickness_adjusting = False
        self.thickness_anchor_mouse = None
        self.thickness_preview_root = None

        obj = bpy.data.objects.get(self._click_object_name) if self._click_object_name else None
        if obj is not None and obj.type == 'CURVE':
            obj["hair_thickness_local_scale"] = self.thickness_preview_scale
            apply_curve_style(obj, context)
            self.pending_local_thickness = None
        else:
            # ainda não existe mecha nesta sessão de clique: guarda o valor e
            # aplica assim que o primeiro clique criar a mecha
            self.pending_local_thickness = self.thickness_preview_scale

    def modal(self, context, event):
        context.area.tag_redraw()

        scene = context.scene
        if not self.resizing:
            self.length = max(0.001, float(scene.hair_guide_length))
        self.lift = float(scene.hair_guide_lift)
        self.angle = float(scene.hair_guide_angle)
        self.tip_taper = float(scene.hair_guide_tip_taper)
        self.curve_amount = float(scene.hair_guide_curve_amount)

        if event.type == 'MOUSEMOVE':
            self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
            if self.resizing:
                self._update_resize_length(context)
            elif self.thickness_adjusting:
                self._update_thickness_scale(context)
            else:
                self._update_hit(context)
            return {'RUNNING_MODAL'}

        if event.type == 'F' and event.value == 'PRESS':
            if self.resizing:
                self.resizing = False
                self.resize_anchor_2d = None
                self.resize_anchor_world = None
                self.resize_root_world = None
            elif not self.thickness_adjusting and self.hit_point is not None:
                self.resizing = True
                self.resize_anchor_2d = self.mouse.copy()
                self.resize_root_world = self.hit_point.copy()
                self.resize_anchor_world = self.hit_point.copy()
                self.resize_original_length = self.length
            return {'RUNNING_MODAL'}

        if event.type == 'S' and event.value == 'PRESS':
            if self.thickness_adjusting:
                self._confirm_thickness(context)
            else:
                if self.hit_point is not None and self.hit_normal is not None:
                    self.thickness_adjusting = True
                    self.thickness_anchor_mouse = self.mouse.copy()
                    obj = bpy.data.objects.get(self._click_object_name) if self._click_object_name else None
                    if obj is not None and obj.type == 'CURVE' and obj.get("hair_thickness_local_scale") is not None:
                        self.thickness_original_scale = obj["hair_thickness_local_scale"]
                    else:
                        self.thickness_original_scale = scene.hair_thickness_scale
                    self.thickness_preview_root = self.hit_point.copy()
                    self.thickness_preview_scale = self.thickness_original_scale
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if self.resizing:
                self.resizing = False
                self.resize_anchor_2d = None
                self.resize_anchor_world = None
                self.resize_root_world = None
                return {'RUNNING_MODAL'}

            if self.thickness_adjusting:
                self._confirm_thickness(context)
                return {'RUNNING_MODAL'}

            if self.hit_point is None or self.hit_normal is None:
                self.report({'WARNING'}, "Nenhuma superfície sob o mouse")
                return {'RUNNING_MODAL'}

            existing_obj = bpy.data.objects.get(self._click_object_name) if self._click_object_name else None
            obj = _new_mecha_object_at(
                context, self.hit_point, self.hit_normal,
                self.length, self.lift, self.angle, self.tip_taper,
                curve_amount=self.curve_amount,
                existing_obj=existing_obj, target=self.target,
            )
            self._click_object_name = obj.name

            if self.pending_local_thickness is not None:
                obj["hair_thickness_local_scale"] = self.pending_local_thickness
                apply_curve_style(obj, context)

            self._created_stack.append(obj.name)
            _select_only(context, obj)
            context.view_layer.update()
            return {'RUNNING_MODAL'}

        if event.type == 'Z' and event.value == 'PRESS':
            if event.ctrl and not event.shift and not event.alt:
                self._undo_last(context)
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}

        if event.type in {
            'NUMPAD_1', 'NUMPAD_2', 'NUMPAD_3', 'NUMPAD_4', 'NUMPAD_5',
            'NUMPAD_6', 'NUMPAD_7', 'NUMPAD_8', 'NUMPAD_9', 'NUMPAD_PERIOD',
        }:
            return {'PASS_THROUGH'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            if self.resizing:
                self.length = self.resize_original_length
                context.scene.hair_guide_length = self.length
                self.resizing = False
                self.resize_anchor_2d = None
                self.resize_anchor_world = None
                self.resize_root_world = None
                return {'RUNNING_MODAL'}

            if self.thickness_adjusting:
                self.thickness_adjusting = False
                self.thickness_anchor_mouse = None
                self.thickness_preview_root = None
                self.thickness_preview_scale = self.thickness_original_scale
                return {'RUNNING_MODAL'}

            self._finish(context)
            return {'CANCELLED'}

        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            if self.resizing:
                self.resizing = False
                self.resize_anchor_2d = None
                self.resize_anchor_world = None
                self.resize_root_world = None
                return {'RUNNING_MODAL'}

            if self.thickness_adjusting:
                self._confirm_thickness(context)
                return {'RUNNING_MODAL'}

            self._finish(context)
            return {'FINISHED'}

        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self._finish(context)

    def _undo_last(self, context):
        if not self._created_stack:
            self.report({'INFO'}, "Nada para desfazer")
            return
        obj_name = self._created_stack.pop()
        obj = bpy.data.objects.get(obj_name)
        if obj is not None and obj.type == 'CURVE':
            removed = _remove_last_spline_from_curve_object(obj)
            if removed and obj_name == self._click_object_name and (obj_name not in bpy.data.objects):
                self._click_object_name = ""
        context.view_layer.update()
        context.area.tag_redraw()
        self.report({'INFO'}, "Última mecha desfeita")

    def _finish(self, context):
        if self._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        context.area.tag_redraw()
