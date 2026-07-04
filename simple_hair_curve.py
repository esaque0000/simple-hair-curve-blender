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


# ---------------------------------------------------------------------
# Perfis de estilização — pequenas curvas 2D usadas como bevel_object.
# Ficam guardadas numa collection escondida "Hair Profiles" pra não
# poluir a cena. São compartilhadas entre todas as curvas de cabelo
# (trocar a espessura de um perfil afeta todas as curvas que o usam —
# se quiser variação por curva, duplique o perfil antes de ajustar).
# ---------------------------------------------------------------------
PROFILE_COLLECTION_NAME = "Hair Profiles"


def get_profile_collection():
    coll = bpy.data.collections.get(PROFILE_COLLECTION_NAME)
    if coll is None:
        coll = bpy.data.collections.new(PROFILE_COLLECTION_NAME)
        bpy.context.scene.collection.children.link(coll)
        # some do view layer sem apagar os dados, só não aparece na cena
        layer_coll = bpy.context.view_layer.layer_collection.children.get(coll.name)
        if layer_coll:
            layer_coll.exclude = True
    return coll


def _new_curve_object(name, points_xy, cyclic, smooth=False):
    """smooth=True usa uma spline NURBS (interpola suavemente entre os
    pontos, como as curvas nativas do Blender) em vez de POLY (linhas
    retas entre os pontos, resultado facetado/rígido)."""
    curve_data = bpy.data.curves.new(name, type='CURVE')
    curve_data.dimensions = '2D'
    spline_type = 'NURBS' if smooth else 'POLY'
    spline = curve_data.splines.new(spline_type)
    spline.points.add(len(points_xy) - 1)
    for i, (x, y) in enumerate(points_xy):
        spline.points[i].co = (x, y, 0.0, 1.0)
    spline.use_cyclic_u = cyclic

    if smooth:
        # order_u não pode passar do número de pontos; e pra curva não
        # fechada precisa tocar as pontas (endpoint) senão ela "encolhe"
        # pra dentro e não passa pelo primeiro/último ponto
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
    """Pra ROUND/STAR, o nome do objeto inclui a configuração (lados,
    suave/rígido) — assim mudar essas opções não reaproveita o perfil
    errado; cada combinação fica com seu próprio objeto na collection
    escondida."""
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


# ---------------------------------------------------------------------
# Perfil customizado — normaliza a escala do objeto escolhido pra
# combinar com o tamanho dos perfis padrão (~0.01), em vez de usar o
# tamanho "cru" que o objeto já tinha (que podia deixar as mechas
# gigantes ou minúsculas dependendo de como a curva foi desenhada).
# A escala "base" fica guardada como custom property no próprio
# objeto, e o slider de Espessura multiplica em cima dela (não
# substitui), então os dois continuam funcionando juntos.
# ---------------------------------------------------------------------
TARGET_PROFILE_RADIUS = 0.01  # mesmo raio padrão do perfil redondo


def _profile_local_max_extent(obj):
    """Maior distância da origem até um ponto de controle da curva, em
    espaço local — usado como 'raio' aproximado do perfil pra escala."""
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
    """Aplica escala = base normalizada × espessura do slider."""
    base = get_profile_base_scale(obj)
    s = base * thickness_scale
    obj.scale = (s, s, s)


def normalize_custom_profile_scale(obj, thickness_scale, force=False):
    """Calcula (uma vez só, a menos que force=True) um fator de escala
    que deixa o perfil customizado do tamanho certo, guarda esse fator
    no próprio objeto, e aplica junto com a espessura atual."""
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
    """Decide qual objeto usar como bevel_object, tratando o caso
    'Customizado' separadamente dos presets (Round/Flat/Square/Star)."""
    scene = context.scene
    kind = scene.hair_profile_kind
    if kind == 'CUSTOM':
        custom = scene.hair_profile_custom
        if custom is not None:
            normalize_custom_profile_scale(custom, scene.hair_thickness_scale)
            return custom
        # sem perfil customizado escolhido ainda: cai pro redondo como
        # padrão seguro, em vez de quebrar
        return get_or_create_profile('ROUND', scene.hair_profile_segments, scene.hair_profile_smooth)
    if kind == 'ROUND':
        return get_or_create_profile('ROUND', scene.hair_profile_segments, scene.hair_profile_smooth)
    if kind == 'STAR':
        return get_or_create_profile('STAR', smooth=scene.hair_profile_smooth)
    return get_or_create_profile(kind)


# ---------------------------------------------------------------------
# Snap — liga as configurações nativas de snap do Blender pra que o
# desenho da curva (Draw Tool nativa, ou extrude com Ctrl+clique) fique
# preso à superfície do mesh selecionado.
# ---------------------------------------------------------------------
def enable_surface_snap(context):
    """Liga snap na superfície. Os nomes exatos de algumas propriedades
    mudaram entre versões do Blender (ex: use_snap_project não existe
    mais em algumas versões 4.x), então cada uma é setada só se existir
    nesta versão — assim o operator nunca quebra por AttributeError."""
    ts = context.scene.tool_settings
    ts.use_snap = True

    if hasattr(ts, "snap_elements"):
        ts.snap_elements = {'FACE'}
    elif hasattr(ts, "snap_elements_base"):
        # Blender 4.x dividiu em base/individual
        ts.snap_elements_base = {'FACE'}

    optional_flags = (
        ("use_snap_align_rotation", True),  # alinha orientação à normal da face
        ("use_snap_project", True),         # projeta na superfície ao mover/extrudar
        ("use_snap_backface_culling", True),
    )
    for attr, value in optional_flags:
        if hasattr(ts, attr):
            setattr(ts, attr, value)
    # "Project Individual Elements" costuma ficar no painel de redo (F9)
    # do próprio operator de mover/extrudar, não é sempre uma propriedade
    # fixa de tool_settings — varia por versão.


# ---------------------------------------------------------------------
# Raycast — em vez de depender do snap nativo (pouco confiável no modo
# de edição de Curve, principalmente no Ctrl+clique de extrude), o
# próprio addon lança o raio da tela contra a cabeça e posiciona cada
# ponto exatamente onde acertou. Assim a curva nunca atravessa o mesh,
# independente de configuração de snap.
# ---------------------------------------------------------------------
SURFACE_OFFSET = 0.0005  # pequeno afastamento ao longo da normal, evita z-fighting
STABILIZER_MAX_WINDOW = 40  # teto do slider de Estabilização (nº de posições do mouse na média)


HAIR_STRAND_PREFIX = "HairStrand"  # usado pra reconhecer objetos de cabelo já desenhados


def raycast_targets(context, coord, targets):
    """Lança o raio da tela contra uma lista de objetos e retorna a
    posição mundial do hit MAIS PRÓXIMO da câmera (já deslocada um
    pouco ao longo da normal), ou None se não acertou nenhum. Isso é o
    que permite desenhar uma mecha grudada na cabeça OU em cima de uma
    mecha já desenhada, dependendo do que estiver mais próximo — dá o
    efeito de camadas/sombra de uma mecha sobre a outra."""
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
    """Lista os objetos Curve já criados por esta ferramenta (identificados
    pelo prefixo do nome), pra poder desenhar mechas novas grudadas em
    cima delas."""
    result = []
    for obj in bpy.data.objects:
        if obj is exclude:
            continue
        if obj.type == 'CURVE' and obj.name.startswith(HAIR_STRAND_PREFIX):
            result.append(obj)
    return result


def sample_point(context, coord, targets, last_point):
    """Tenta grudar na superfície (cabeça e, se habilitado, mechas já
    desenhadas) via raycast a partir de coord (x, y em coordenadas da
    região); se não acertar nada, cai pra um ponto livre no espaço,
    projetado na profundidade do último ponto do traço — assim o
    desenho continua naturalmente formando cachos que saem do couro
    cabeludo, em vez de simplesmente parar de adicionar pontos."""
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
    """Adiciona uma nova spline (POLY) ao objeto Curve existente, a
    partir de uma lista de posições em espaço de mundo."""
    curve_data = curve_obj.data
    matrix_inv = curve_obj.matrix_world.inverted()

    spline = curve_data.splines.new('POLY')
    spline.points.add(len(world_points) - 1)
    for i, p in enumerate(world_points):
        local = matrix_inv @ p
        spline.points[i].co = (local.x, local.y, local.z, 1.0)
    return spline


# ---------------------------------------------------------------------
# Afinamento — usa o atributo "radius" de cada ponto da spline, que
# escala o perfil de bevel localmente (funciona com qualquer perfil:
# redondo, flat, quadrado, estrela ou customizado). Serve pra simular
# um fio de cabelo real (afina nas pontas) sem precisar de um perfil
# separado. Pode afinar só a ponta final, só a raiz, ou as duas —
# pra dreads/mechas grossas basta deixar desligado (espessura uniforme).
# ---------------------------------------------------------------------
def apply_taper_to_spline(spline, fraction, tip_radius, mode):
    """mode: 'TIP' (afina o final do traço), 'ROOT' (afina o início),
    ou 'BOTH' (afina as duas pontas, cada uma com sua própria fração/
    espessura, sem se sobrepor no meio da mecha)."""
    points = spline.points
    n = len(points)
    if n < 2 or mode == 'OFF':
        reset_spline_radius(spline)
        return

    # zera tudo primeiro pra não sobrar afinamento de uma config antiga
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
    """Volta todos os pontos da spline pra espessura uniforme (radius 1.0)."""
    for point in spline.points:
        point.radius = 1.0


# ---------------------------------------------------------------------
# Preview GPU — desenha em tempo real, sobre o viewport, os pontos já
# raycastados do traço em andamento (tanto no modo Livre quanto no
# modo por clique). Sem isso o traço fica "cego" até ser confirmado.
# O nome do shader uniforme mudou entre versões do Blender (3.x usa o
# prefixo "3D_", 4.x não), então tentamos os dois e guardamos qual
# funcionou em cache, pra não ficar tentando toda hora.
# ---------------------------------------------------------------------
_UNIFORM_SHADER_CACHE = None

STROKE_PREVIEW_COLOR = (1.0, 0.55, 0.1, 0.95)   # laranja: traço em andamento
STROKE_PREVIEW_POINT_COLOR = (1.0, 0.9, 0.2, 1.0)  # ponto do início do traço


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
    """Desenha o traço em andamento (lista de posições em espaço de
    mundo) como uma linha, e um ponto destacado na origem do traço pra
    deixar claro onde ele começou."""
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


# ---------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------
class HAIR_OT_draw_strand(bpy.types.Operator):
    """Desenha mechas continuamente, com preview ao vivo no viewport.
    Modo Livre: clique e arraste sobre a cabeça pra grudar na
    superfície, ou continue arrastando pra fora dela pra formar cachos
    soltos no espaço; solte o botão pra confirmar. Modo Contínuo: clique
    uma vez pra começar, mova o mouse (a mecha vai grudando na
    superfície em tempo real, exatamente como no Livre, só que sem
    precisar segurar o botão), e clique de novo ou aperte Enter pra
    terminar — como cada ponto já vem do raycast seguindo o mouse, a
    mecha nunca atravessa a cabeça em linha reta. A primeira mecha cria
    o objeto Curve e entra em modo de edição automaticamente; as
    próximas viram novas splines desse mesmo objeto. Ctrl+Z desfaz a
    última mecha confirmada. Navegue a view livremente a qualquer
    momento. Space encerra a ferramenta."""
    bl_idname = "hair.draw_strand"
    bl_label = "Desenhar Mechas"
    bl_options = {'REGISTER', 'UNDO'}

    # eventos de navegação que devem passar direto pro viewport em vez
    # de serem interceptados pela ferramenta
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
        self.points = []
        self.raw_coords = []
        self.drawing = False
        self.strand_count = 0

        # continua na mecha ativa se houver uma selecionada no viewport,
        # senão na última mecha lembrada pela cena; None só se realmente
        # não houver nenhuma (aí o primeiro traço cria uma nova)
        active_obj = context.active_object
        if (active_obj is not None and active_obj.type == 'CURVE'
                and active_obj.name.startswith(HAIR_STRAND_PREFIX)):
            self.curve_obj = active_obj
        else:
            self.curve_obj = context.scene.hair_active_curve

        self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_callback, (), 'WINDOW', 'POST_VIEW'
        )

        context.window_manager.modal_handler_add(self)
        self._update_status_text(context)
        return {'RUNNING_MODAL'}

    def _draw_callback(self):
        """Chamado pelo Blender a cada redraw do viewport enquanto o
        modal está ativo — desenha o traço em andamento (self.points),
        tanto no modo Livre (durante o arraste) quanto no modo Contínuo
        (entre o clique inicial e o clique/Enter final)."""
        if self.drawing:
            draw_stroke_preview(self.points)

    def _remove_draw_handler(self):
        if getattr(self, "_draw_handler", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handler, 'WINDOW')
            self._draw_handler = None

    def _update_status_text(self, context):
        if context.scene.hair_draw_mode == 'TWO_POINT':
            if not self.drawing:
                context.workspace.status_text_set(
                    "Clique pra começar a mecha. Ctrl+Z desfaz a última "
                    "mecha. Space encerra a ferramenta."
                )
            else:
                context.workspace.status_text_set(
                    "Mova o mouse pra traçar (gruda na superfície ao vivo). "
                    "Clique ou Enter termina a mecha. Botão direito ou Esc "
                    "cancela o traço atual."
                )
        else:
            context.workspace.status_text_set(
                "Clique e arraste: na cabeça gruda na superfície, fora dela forma cachos soltos. "
                "Ctrl+Z desfaz a última mecha. Space encerra a ferramenta."
            )

    def modal(self, context, event):
        # Deixa passar direto pro Blender qualquer evento fora da área
        # principal do Viewport 3D: painel N (barra lateral), outros
        # editores (Propriedades, Outliner...), abas de workspace, etc.
        # Isso é o que permite usar os controles do addon e o resto da
        # interface sem precisar apertar Space pra "sair" da ferramenta
        # antes. Só o clique dentro do viewport 3D em si é interpretado
        # como desenho.
        if context.area is None or context.area.type != 'VIEW_3D':
            return {'PASS_THROUGH'}
        if context.region is None or context.region.type != 'WINDOW':
            return {'PASS_THROUGH'}

        context.area.tag_redraw()

        two_point_mode = context.scene.hair_draw_mode == 'TWO_POINT'

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if not self.drawing:
                # começa um traço novo — igual nos dois modos
                self.drawing = True
                self.points = []
                self.raw_coords = []
                self._add_point(context, event)
                if two_point_mode:
                    self._update_status_text(context)
                return {'RUNNING_MODAL'}
            elif two_point_mode:
                # segundo clique no modo Contínuo termina o traço
                self._end_stroke(context)
                return {'RUNNING_MODAL'}
            # no modo Livre um clique nesse estado não faz nada (quem
            # termina o traço é o RELEASE, abaixo)
            return {'RUNNING_MODAL'}

        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE' and not two_point_mode:
            self._end_stroke(context)
            return {'RUNNING_MODAL'}  # segue esperando o próximo traço

        elif event.type == 'MOUSEMOVE' and self.drawing:
            self._add_point(context, event)

        elif (event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS'
                and two_point_mode and self.drawing):
            self._end_stroke(context)
            return {'RUNNING_MODAL'}

        elif event.type == 'Z' and event.ctrl and event.value == 'PRESS' and not self.drawing:
            self._undo_last_stroke(context)
            return {'RUNNING_MODAL'}

        elif event.type == 'SPACE' and event.value == 'PRESS' and not self.drawing:
            self._remove_draw_handler()
            context.workspace.status_text_set(None)
            if self.curve_obj is not None:
                self.report(
                    {'INFO'},
                    f"{self.strand_count} mecha(s) nesta sessão. "
                    f"'{self.curve_obj.name}' continua ativa — reabra a "
                    "ferramenta pra continuar nela, ou use 'Nova Mecha'."
                )
            else:
                self.report({'INFO'}, f"{self.strand_count} mecha(s) criada(s)")
            return {'FINISHED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'} and self.drawing:
            # cancela só o traço em andamento (em qualquer modo), sem
            # sair da ferramenta
            self.drawing = False
            self.points = []
            self.raw_coords = []
            if two_point_mode:
                self._update_status_text(context)
            return {'RUNNING_MODAL'}

        elif event.type == 'ESC' and not self.drawing:
            # fora de um traço, Esc também encerra a ferramenta (Space é o principal)
            self._remove_draw_handler()
            context.workspace.status_text_set(None)
            return {'FINISHED'}

        elif event.type in self.NAV_PASSTHROUGH:
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}

    def _end_stroke(self, context):
        """Termina o traço em andamento (RELEASE no modo Livre, ou
        segundo clique/Enter no modo Contínuo) e confirma a mecha se
        ela tiver pontos suficientes."""
        self.drawing = False
        if len(self.points) >= 2:
            self._commit_stroke(context)
        else:
            self.report({'WARNING'}, "Mecha muito curta, ignorada")
        self.points = []
        if context.scene.hair_draw_mode == 'TWO_POINT':
            self._update_status_text(context)

    def _get_raycast_targets(self, context):
        """Monta a lista de objetos contra os quais o raycast é testado:
        a cabeça sempre, e as mechas já desenhadas se a opção de
        sobreposição estiver ligada (exceto a própria curva em edição,
        pra não colidir com o traço que ainda está sendo desenhado)."""
        targets = [self.target]
        if context.scene.hair_overlap_hair:
            targets.extend(collect_existing_hair_objects(exclude=self.curve_obj))
        return targets

    def _add_point(self, context, event):
        last = self.points[-1] if self.points else None
        raw_coord = (event.mouse_region_x, event.mouse_region_y)

        # guarda só as últimas STABILIZER_MAX_WINDOW posições — é tudo
        # que a estabilização pode precisar, então não faz sentido
        # deixar a lista crescer sem limite num traço longo
        self.raw_coords.append(raw_coord)
        if len(self.raw_coords) > STABILIZER_MAX_WINDOW:
            self.raw_coords = self.raw_coords[-STABILIZER_MAX_WINDOW:]

        coord = self._stabilized_coord(context)
        targets = self._get_raycast_targets(context)
        p = sample_point(context, coord, targets, last)
        if p is None:
            return
        if not self.points or (p - self.points[-1]).length > 0.002:
            self.points.append(p)

    def _stabilized_coord(self, context):
        """Faz a média das últimas N posições cruas do mouse (N = valor
        do slider de Estabilização, até STABILIZER_MAX_WINDOW) antes de
        raycastar — isso funciona como um filtro passa-baixa sobre o
        movimento do mouse, removendo a tremedeira de alta frequência
        (tipo estabilização de imagem/vídeo) às custas de um pequeno
        atraso entre o cursor e o ponto desenhado. 0 desliga (usa a
        posição crua, sem atraso)."""
        window = max(1, min(context.scene.hair_stroke_stabilizer, len(self.raw_coords)))
        recent = self.raw_coords[-window:]
        avg_x = sum(c[0] for c in recent) / len(recent)
        avg_y = sum(c[1] for c in recent) / len(recent)
        return (avg_x, avg_y)

    def _commit_stroke(self, context):
        """Confirma o traço atual: cria o objeto Curve na primeira vez
        (e entra em modo de edição), ou adiciona uma spline nova nas
        vezes seguintes. Sai do Edit Mode brevemente pra mexer nos
        dados de baixo nível e volta em seguida, senão a edição de
        curva do Blender pode ficar dessincronizada."""
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
            context.collection.objects.link(self.curve_obj)

        # garante que a mecha (nova ou retomada de uma sessão anterior)
        # é a que fica ativa/selecionada antes de entrar em Edit Mode —
        # senão o mode_set abaixo editaria qualquer outro objeto que
        # estivesse ativo no momento
        for other in context.selected_objects:
            if other is not self.curve_obj:
                other.select_set(False)
        context.view_layer.objects.active = self.curve_obj
        self.curve_obj.select_set(True)

        scene = context.scene
        spline = add_spline_from_points(self.curve_obj, self.points)

        if scene.hair_taper_mode != 'OFF':
            apply_taper_to_spline(
                spline, scene.hair_taper_fraction, scene.hair_taper_tip_radius,
                scene.hair_taper_mode
            )

        self.strand_count += 1

        context.scene.hair_active_curve = self.curve_obj

        bpy.ops.object.mode_set(mode='EDIT')

    def _undo_last_stroke(self, context):
        """Remove a última spline confirmada. Em vez de guardar uma
        referência ao objeto Spline (que fica inválida depois de
        trocar de modo OBJECT/EDIT, já que o Blender reconstrói os
        dados internos da curva), sempre pega a última spline da lista
        atual — como mechas só são adicionadas no final, isso é
        equivalente e nunca aponta pra memória obsoleta."""
        if self.curve_obj is None or len(self.curve_obj.data.splines) == 0:
            self.report({'INFO'}, "Nada para desfazer")
            return

        self.strand_count -= 1

        was_edit = context.mode == 'EDIT_CURVE'
        if was_edit:
            bpy.ops.object.mode_set(mode='OBJECT')

        splines = self.curve_obj.data.splines
        splines.remove(splines[-1])

        if len(splines) == 0:
            data = self.curve_obj.data
            obj_to_remove = self.curve_obj
            self.curve_obj = None
            context.scene.hair_active_curve = None
            bpy.data.objects.remove(obj_to_remove, do_unlink=True)
            bpy.data.curves.remove(data)
        elif was_edit:
            bpy.ops.object.mode_set(mode='EDIT')

        self.report({'INFO'}, "Última mecha desfeita")


class HAIR_OT_new_strand(bpy.types.Operator):
    """Esquece a mecha ativa: o próximo traço desenhado vai criar um
    objeto Curve novo, em vez de continuar adicionando splines na
    mecha atual"""
    bl_idname = "hair.new_strand"
    bl_label = "Nova Mecha"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.hair_active_curve = None
        self.report({'INFO'}, "Próximo traço vai criar uma mecha nova")
        return {'FINISHED'}


class HAIR_OT_toggle_snap(bpy.types.Operator):
    """Liga/desliga o snap de superfície manualmente"""
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
    """Recalcula a escala normalizada do perfil customizado — use se
    você redimensionar a curva escolhida em 'Perfil Customizado' depois
    de já ter usado ela aqui"""
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
    """Aplica o perfil de estilização selecionado à curva ativa"""
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
    """Aplica (ou remove, se o modo estiver 'Desligado') o afinamento
    em todas as splines da curva ativa, usando as configurações atuais"""
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
    """Ajusta a espessura do perfil aplicado à curva ativa (multiplica
    a escala base do perfil, então funciona certo tanto pros perfis
    padrão quanto pro customizado normalizado)"""
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


# ---------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------
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
        active_row = layout.row(align=True)
        if scene.hair_active_curve is not None:
            active_row.label(text=f"Mecha ativa: {scene.hair_active_curve.name}", icon='CURVE_DATA')
        else:
            active_row.label(text="Mecha ativa: nenhuma", icon='CURVE_DATA')
        active_row.operator("hair.new_strand", text="", icon='ADD')

        layout.separator()
        col = layout.column(align=True)
        col.prop(scene, "hair_draw_mode", text="Modo")
        col.prop(scene, "hair_stroke_stabilizer", text="Estabilização", slider=True)
        col.operator("hair.draw_strand", icon='CURVE_DATA')
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
        info.label(text="  2. 'Desenhar Mechas': clique+arraste")
        info.label(text="     na cabeça gruda; fora dela, cacho")
        info.label(text="     livre. Ctrl+Z desfaz a última.")
        info.label(text="     Space termina — a mecha continua")
        info.label(text="     ativa pra você retomar depois.")


# ---------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------
classes = (
    HAIR_OT_draw_strand,
    HAIR_OT_new_strand,
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
        description="Número de lados do perfil redondo. Poucos lados "
                    "(3-5) dão um visual mais facetado, bom pra mechas "
                    "volumosas/estilizadas; mais lados (8+) dão um "
                    "cilindro mais liso"
    )
    bpy.types.Scene.hair_profile_smooth = bpy.props.BoolProperty(
        name="Suavizar perfil", default=True,
        description="Usa uma curva NURBS suave (como as curvas nativas "
                    "do Blender) em vez de linhas retas entre os pontos. "
                    "Desligue pra manter o visual facetado/rígido — útil "
                    "junto com poucos 'Lados' pra um efeito de mecha "
                    "volumosa/estilizada, tipo dread"
    )
    bpy.types.Scene.hair_thickness_scale = bpy.props.FloatProperty(
        name="Espessura", default=1.0, min=0.01, max=10.0
    )

    bpy.types.Scene.hair_active_curve = bpy.props.PointerProperty(
        name="Mecha Ativa", type=bpy.types.Object,
        description="Última curva de cabelo editada. 'Desenhar Mechas' "
                    "continua adicionando traços nela em vez de criar "
                    "uma nova — use 'Nova Mecha' pra começar outra",
        poll=lambda self, obj: obj.type == 'CURVE' and obj.name.startswith(HAIR_STRAND_PREFIX)
    )

    bpy.types.Scene.hair_overlap_hair = bpy.props.BoolProperty(
        name="Sobrepor em cabelo já desenhado", default=False,
        description="Além da cabeça, o raycast também tenta grudar em "
                    "mechas já desenhadas (a superfície mais próxima da "
                    "câmera 'ganha') — dá um efeito de camadas, com "
                    "sombra de uma mecha sobre a outra. Pode ficar mais "
                    "lento com muitas mechas na cena"
    )
    bpy.types.Scene.hair_draw_mode = bpy.props.EnumProperty(
        name="Modo de desenho", default='FREE',
        items=[
            ('FREE', "Livre (arrastar)", "Clique e arraste continuamente pra desenhar a mecha; solte pra confirmar"),
            ('TWO_POINT', "Contínuo (clique p/ começar/parar)",
             "Clique pra começar, mova o mouse pra traçar (gruda na "
             "superfície ao vivo, sem precisar segurar o botão), e "
             "clique de novo ou aperte Enter pra terminar"),
        ],
        description="Como cada mecha é desenhada"
    )

    bpy.types.Scene.hair_stroke_stabilizer = bpy.props.IntProperty(
        name="Estabilização", default=0, min=0, max=STABILIZER_MAX_WINDOW,
        description="Suaviza o traço fazendo uma média das últimas N "
                    "posições do mouse antes de raycastar (tipo "
                    "estabilização de imagem: reduz a tremedeira). 0 "
                    "desliga; valores altos deixam a linha mais lisa, "
                    "mas com mais atraso entre o cursor e o ponto "
                    "desenhado"
    )

    bpy.types.Scene.hair_taper_mode = bpy.props.EnumProperty(
        name="Afinar", default='OFF',
        items=[
            ('OFF', "Desligado", "Espessura uniforme (bom pra dreads/mechas grossas)"),
            ('TIP', "Só na ponta final", "Afina só o final do traço"),
            ('ROOT', "Só na raiz", "Afina só o início do traço"),
            ('BOTH', "Nas duas pontas", "Afina início e fim do traço"),
        ],
        description="Onde a mecha afina, simulando um fio de cabelo "
                    "real. O lado 'ponta final'/'raiz' depende de qual "
                    "ponta você desenhou primeiro"
    )
    bpy.types.Scene.hair_taper_fraction = bpy.props.FloatProperty(
        name="Trecho afinado", default=0.35, min=0.05, max=1.0,
        subtype='FACTOR',
        description="Que parte do traço participa do afinamento em "
                    "cada ponta afinada"
    )
    bpy.types.Scene.hair_taper_tip_radius = bpy.props.FloatProperty(
        name="Espessura na ponta", default=0.05, min=0.0, max=1.0,
        subtype='FACTOR',
        description="Espessura relativa no ponto mais fino (0 = afina "
                    "até quase desaparecer, 1 = sem afinamento)"
    )


def unregister():
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
    del bpy.types.Scene.hair_taper_mode
    del bpy.types.Scene.hair_taper_fraction
    del bpy.types.Scene.hair_taper_tip_radius

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
