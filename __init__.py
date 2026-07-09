bl_info = {
    "name": "Simple Hair Curve",
    "author": "Esaque",
    "version": (1, 5, 0),
    "blender": (4, 3, 0),
    "location": "View3D > Sidebar > Hair",
    "description": "Editor de mechas em curvas com criação guiada na superfície, curvatura controlável, perfis de estilização, orientação estável e crescimento pela pintura de vertex group.",
    "category": "Curve",
}

import bpy

from .core import (
    DEFAULT_GUIDE_LENGTH,
    DEFAULT_GUIDE_LIFT,
    DEFAULT_GUIDE_ANGLE,
    DEFAULT_GUIDE_CURVE,
    DEFAULT_GUIDE_TIP_TAPER,
    DEFAULT_ROOT_EMBED_DEPTH,
    DEFAULT_GROWTH_COUNT,
    DEFAULT_GROWTH_LENGTH_VARIATION,
    DEFAULT_GROWTH_ANGLE_VARIATION,
    DEFAULT_GROWTH_SEED,
    DEFAULT_GROWTH_MIN_SPACING,
    DEFAULT_GROWTH_SPACING_ATTEMPTS,
    DEFAULT_GROWTH_MIRROR,
    DEFAULT_GROWTH_FILL_MODE,
    DEFAULT_GROWTH_WEIGHT_THRESHOLD,
    DEFAULT_GROWTH_WEIGHT_AFFECTS_LENGTH,
    DEFAULT_GROWTH_LENGTH_WEIGHT_MIN,
    DEFAULT_GROWTH_WEIGHT_AFFECTS_THICKNESS,
    DEFAULT_GROWTH_THICKNESS_WEIGHT_MIN,
    DEFAULT_GROWTH_TIP_TAPER,
    DEFAULT_CLOSE_TIPS,
    DEFAULT_COMB_RADIUS,
    DEFAULT_COMB_STRENGTH,
    DEFAULT_COMB_PIN_ROOT,
    _on_style_property_change,
    _on_profile_custom_change,
    _on_guide_property_change,
)
from .operators import (
    HAIR_OT_snap_active_mecha,
    HAIR_OT_normalize_custom_profile,
    HAIR_OT_apply_profile,
    HAIR_OT_set_thickness,
    HAIR_OT_reset_local_thickness,
    HAIR_OT_apply_style_now,
    HAIR_OT_apply_guide_now,
    HAIR_OT_convert_active_to_light_mesh,
    HAIR_OT_open_weight_paint,
    HAIR_OT_create_vertex_group,
    HAIR_OT_apply_growth_from_paint,
    HAIR_OT_comb_brush,
    HAIR_OT_create_mecha_brush,
)
from .ui import HAIR_PT_panel


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------


classes = (
    HAIR_OT_snap_active_mecha,
    HAIR_OT_normalize_custom_profile,
    HAIR_OT_apply_profile,
    HAIR_OT_set_thickness,
    HAIR_OT_reset_local_thickness,
    HAIR_OT_apply_style_now,
    HAIR_OT_apply_guide_now,
    HAIR_OT_convert_active_to_light_mesh,
    HAIR_OT_open_weight_paint,
    HAIR_OT_create_vertex_group,
    HAIR_OT_apply_growth_from_paint,
    HAIR_OT_comb_brush,
    HAIR_OT_create_mecha_brush,
    HAIR_PT_panel,
)

PROFILE_ITEMS = [
    ('CLUMP', "Tufo (perfil composto)", "Uma linha guia só, mas o perfil já é um pequeno feixe de mini-fios agrupados"),
    ('ROUND', "Redondo (perfil com malha)", "Fio cilíndrico clássico, com malha de perfil própria"),
    ('FLAT', "Fita (Flat)", "Fita achatada, com curvatura opcional"),
    ('SQUARE', "Quadrado", "Seção quadrada"),
    ('STAR', "Estrela", "Seção estilizada em estrela"),
    ('CUSTOM', "Customizado", "Use qualquer curva 2D como perfil"),
]

STYLE_APPLY_SCOPE_ITEMS = [
    ('ACTIVE', "Curva ativa", "O auto-aplicar afeta apenas a curva de cabelo selecionada/ativa"),
    ('ALL', "Todas as mechas", "O auto-aplicar afeta todas as curvas de cabelo (HairMecha/HairGrowth) da cena"),
]

TAPER_MODE_ITEMS = [
    ('TIP', "Afina ponta", "Mantém a raiz mais grossa e afina a ponta"),
    ('ROOT', "Afina raiz", "Afina a raiz e mantém a ponta mais grossa"),
    ('BOTH', "Afina ambas", "Afina raiz e ponta, deixando o meio mais cheio"),
    ('NONE', "Sem afinar", "Mantém a espessura uniforme"),
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.hair_surface_target = bpy.props.PointerProperty(
        name="Superfície", type=bpy.types.Object,
        description="Mesh da cabeça onde as mechas serão guiadas",
        poll=lambda self, obj: obj.type == 'MESH'
    )

    bpy.types.Scene.hair_close_tips = bpy.props.BoolProperty(
        name="Fechar pontas", default=DEFAULT_CLOSE_TIPS,
        description="Fecha as extremidades (tampas) dos tubos das mechas para não ver por dentro dos fios",
        update=_on_style_property_change,
    )

    bpy.types.Scene.hair_root_embed_depth = bpy.props.FloatProperty(
        name="Profundidade da raiz", default=DEFAULT_ROOT_EMBED_DEPTH, min=0.0, max=0.2,
        soft_max=0.03, subtype='DISTANCE',
        description="Empurra a raiz da mecha para dentro da cabeça, deixando-a embutida na malha em vez de apenas tangente à superfície"
    )

    bpy.types.Scene.hair_guide_length = bpy.props.FloatProperty(
        name="Comprimento", default=DEFAULT_GUIDE_LENGTH, min=0.01, max=10.0,
        subtype='DISTANCE',
        description="Comprimento inicial da mecha-guia",
        update=_on_guide_property_change,
    )
    bpy.types.Scene.hair_guide_lift = bpy.props.FloatProperty(
        name="Elevação", default=DEFAULT_GUIDE_LIFT, min=0.0, max=2.0,
        subtype='FACTOR',
        description="Quanto a mecha sobe para fora da cabeça no guia inicial",
        update=_on_guide_property_change,
    )
    bpy.types.Scene.hair_guide_angle = bpy.props.FloatProperty(
        name="Ângulo", default=DEFAULT_GUIDE_ANGLE, min=-180.0, max=180.0,
        subtype='ANGLE',
        description="Rotação da direção inicial da mecha em torno da normal",
        update=_on_guide_property_change,
    )
    bpy.types.Scene.hair_guide_tip_taper = bpy.props.FloatProperty(
        name="Afinar ponta", default=DEFAULT_GUIDE_TIP_TAPER, min=0.02, max=1.0,
        subtype='FACTOR',
        description="Afina a ponta da mecha-guia em relação à espessura da raiz",
        update=_on_guide_property_change,
    )
    bpy.types.Scene.hair_guide_curve_amount = bpy.props.FloatProperty(
        name="Curvatura", default=DEFAULT_GUIDE_CURVE, min=0.0, max=1.0,
        subtype='FACTOR',
        description="Controla a curva da guia: 0 = totalmente reto, 1 = curvatura mais marcada",
        update=_on_guide_property_change,
    )
    bpy.types.Scene.hair_guide_live_update = bpy.props.BoolProperty(
        name="Atualizar guia ao vivo", default=True,
        description=(
            "Quando ligado, mexer em Comprimento/Elevação/Ângulo/Curvatura/Afinar ponta "
            "reconstrói imediatamente as mechas já criadas (no escopo escolhido abaixo, "
            "'Curva ativa' ou 'Todas as mechas'), mantendo a raiz de cada fio no lugar. "
            "Se desligado, use o botão 'Aplicar Guia Agora'"
        ),
    )

    bpy.types.Scene.hair_growth_vertex_group = bpy.props.StringProperty(
        name="Vertex Group",
        default="HairGrowth",
        description="Vertex group pintado no couro cabeludo usado como máscara de crescimento"
    )
    bpy.types.Scene.hair_new_vertex_group_name = bpy.props.StringProperty(
        name="Novo Vertex Group",
        default="HairGrowth",
        description="Nome para criar um novo vertex group"
    )
    bpy.types.Scene.hair_growth_count = bpy.props.IntProperty(
        name="Quantidade", default=DEFAULT_GROWTH_COUNT, min=1, max=50000,
        description="Quantidade de fios gerados a partir da pintura"
    )
    bpy.types.Scene.hair_growth_length_variation = bpy.props.FloatProperty(
        name="Variação de tamanho", default=DEFAULT_GROWTH_LENGTH_VARIATION, min=0.0, max=1.0,
        subtype='FACTOR',
        description="Variação aleatória aplicada ao comprimento de cada fio"
    )
    bpy.types.Scene.hair_growth_angle_variation = bpy.props.FloatProperty(
        name="Variação de direção", default=DEFAULT_GROWTH_ANGLE_VARIATION, min=0.0, max=180.0,
        subtype='ANGLE',
        description="Variação aleatória na direção de crescimento de cada fio"
    )
    bpy.types.Scene.hair_growth_min_spacing = bpy.props.FloatProperty(
        name="Espaçamento mínimo", default=DEFAULT_GROWTH_MIN_SPACING, min=0.0, max=1.0,
        subtype='DISTANCE',
        description="Distância mínima aproximada entre raízes para evitar fios colados"
    )
    bpy.types.Scene.hair_growth_spacing_attempts = bpy.props.IntProperty(
        name="Tentativas de espaço", default=DEFAULT_GROWTH_SPACING_ATTEMPTS, min=1, max=50,
        description="Número de tentativas para achar espaço antes de aceitar a raiz"
    )
    bpy.types.Scene.hair_growth_mirror_other_side = bpy.props.BoolProperty(
        name="Espelhar outro lado", default=DEFAULT_GROWTH_MIRROR,
        description="Cria um fio espelhado para cada fio gerado"
    )
    bpy.types.Scene.hair_growth_fill_mode = bpy.props.BoolProperty(
        name="Priorizar vazios", default=DEFAULT_GROWTH_FILL_MODE,
        description="Tenta preencher primeiro as áreas menos ocupadas da pintura"
    )
    bpy.types.Scene.hair_growth_seed = bpy.props.IntProperty(
        name="Seed", default=DEFAULT_GROWTH_SEED, min=0, max=999999,
        description="Seed para refazer o crescimento de forma reproduzível"
    )
    bpy.types.Scene.hair_growth_result_object = bpy.props.StringProperty(
        name="Resultado do crescimento",
        default="",
        description="Nome do último objeto gerado pela pintura"
    )

    bpy.types.Scene.hair_growth_weight_threshold = bpy.props.FloatProperty(
        name="Peso mínimo", default=DEFAULT_GROWTH_WEIGHT_THRESHOLD, min=0.0, max=0.99,
        subtype='FACTOR',
        description="Áreas com peso pintado abaixo deste valor são tratadas como não pintadas e não geram fios"
    )
    bpy.types.Scene.hair_growth_weight_affects_length = bpy.props.BoolProperty(
        name="Peso afeta comprimento", default=DEFAULT_GROWTH_WEIGHT_AFFECTS_LENGTH,
        description="Fios em áreas mais fracamente pintadas ficam mais curtos"
    )
    bpy.types.Scene.hair_growth_length_weight_min = bpy.props.FloatProperty(
        name="Comprimento mínimo", default=DEFAULT_GROWTH_LENGTH_WEIGHT_MIN, min=0.05, max=1.0,
        subtype='FACTOR',
        description="Fração mínima do comprimento nas áreas pintadas próximas do peso mínimo"
    )
    bpy.types.Scene.hair_growth_weight_affects_thickness = bpy.props.BoolProperty(
        name="Peso afeta espessura", default=DEFAULT_GROWTH_WEIGHT_AFFECTS_THICKNESS,
        description="Fios em áreas mais fracamente pintadas ficam mais finos"
    )
    bpy.types.Scene.hair_growth_thickness_weight_min = bpy.props.FloatProperty(
        name="Espessura mínima", default=DEFAULT_GROWTH_THICKNESS_WEIGHT_MIN, min=0.05, max=1.0,
        subtype='FACTOR',
        description="Fração mínima da espessura nas áreas pintadas próximas do peso mínimo"
    )
    bpy.types.Scene.hair_growth_tip_taper = bpy.props.FloatProperty(
        name="Afinamento da ponta", default=DEFAULT_GROWTH_TIP_TAPER, min=0.05, max=1.0,
        subtype='FACTOR',
        description="Quanto a ponta de cada fio afina em relação à raiz"
    )

    bpy.types.Scene.hair_comb_radius = bpy.props.FloatProperty(
        name="Raio da escova", default=DEFAULT_COMB_RADIUS, min=5.0, max=500.0,
        description="Raio do pincel de pentear, em pixels de tela"
    )
    bpy.types.Scene.hair_comb_strength = bpy.props.FloatProperty(
        name="Força da escova", default=DEFAULT_COMB_STRENGTH, min=0.01, max=3.0,
        subtype='FACTOR',
        description="Intensidade do efeito da escova a cada movimento do mouse"
    )
    bpy.types.Scene.hair_comb_pin_root = bpy.props.BoolProperty(
        name="Fixar raiz", default=DEFAULT_COMB_PIN_ROOT,
        description="Mantém a raiz da mecha presa à superfície enquanto penteia"
    )

    bpy.types.Scene.hair_style_apply_scope = bpy.props.EnumProperty(
        name="Escopo do auto-aplicar", items=STYLE_APPLY_SCOPE_ITEMS, default='ACTIVE',
        description="Define se as mudanças de perfil/espessura/afinação/tampas/guia são aplicadas automaticamente só na curva ativa ou em todas as mechas da cena"
    )

    bpy.types.Scene.hair_profile_kind = bpy.props.EnumProperty(
        name="Perfil", items=PROFILE_ITEMS, default='ROUND',
        update=_on_style_property_change,
    )
    bpy.types.Scene.hair_profile_custom = bpy.props.PointerProperty(
        name="Perfil Customizado", type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'CURVE',
        update=_on_profile_custom_change,
    )
    bpy.types.Scene.hair_profile_segments = bpy.props.IntProperty(
        name="Lados do perfil", default=8, min=3, max=32
    )
    bpy.types.Scene.hair_profile_smooth = bpy.props.BoolProperty(
        name="Suavizar perfil", default=True,
        update=_on_style_property_change,
    )
    bpy.types.Scene.hair_profile_flat_arc_depth = bpy.props.FloatProperty(
        name="Curvatura (arco)", default=0.2, min=0.0, max=0.8,
        subtype='FACTOR'
    )
    bpy.types.Scene.hair_profile_flat_segments = bpy.props.IntProperty(
        name="Segmentos do arco", default=7, min=3, max=16
    )
    bpy.types.Scene.hair_profile_clump_count = bpy.props.IntProperty(
        name="Fios no perfil", default=5, min=2, max=24
    )
    bpy.types.Scene.hair_profile_clump_spread = bpy.props.FloatProperty(
        name="Raio do feixe", default=0.006, min=0.001, max=0.03,
        soft_max=0.015, subtype='DISTANCE'
    )
    bpy.types.Scene.hair_profile_clump_strand_radius = bpy.props.FloatProperty(
        name="Espessura de cada fio", default=0.0015, min=0.0002, max=0.01,
        soft_max=0.004, subtype='DISTANCE'
    )
    bpy.types.Scene.hair_taper_mode = bpy.props.EnumProperty(
        name="Afinação", items=TAPER_MODE_ITEMS, default='TIP',
        description="Escolhe se o fio afina na ponta, na raiz, em ambas ou em nenhuma",
        update=_on_style_property_change,
    )
    bpy.types.Scene.hair_thickness_scale = bpy.props.FloatProperty(
        name="Espessura", default=1.0, min=0.01, max=10.0,
        update=_on_style_property_change,
    )
    bpy.types.Scene.hair_mesh_reduction_ratio = bpy.props.FloatProperty(
        name="Redução de polígonos", default=0.35, min=0.05, max=1.0,
        subtype='FACTOR'
    )


def unregister():
    del bpy.types.Scene.hair_surface_target
    del bpy.types.Scene.hair_close_tips
    del bpy.types.Scene.hair_root_embed_depth
    del bpy.types.Scene.hair_guide_length
    del bpy.types.Scene.hair_guide_lift
    del bpy.types.Scene.hair_guide_angle
    del bpy.types.Scene.hair_guide_tip_taper
    del bpy.types.Scene.hair_guide_curve_amount
    del bpy.types.Scene.hair_guide_live_update
    del bpy.types.Scene.hair_growth_vertex_group
    del bpy.types.Scene.hair_new_vertex_group_name
    del bpy.types.Scene.hair_growth_count
    del bpy.types.Scene.hair_growth_length_variation
    del bpy.types.Scene.hair_growth_angle_variation
    del bpy.types.Scene.hair_growth_min_spacing
    del bpy.types.Scene.hair_growth_spacing_attempts
    del bpy.types.Scene.hair_growth_mirror_other_side
    del bpy.types.Scene.hair_growth_fill_mode
    del bpy.types.Scene.hair_growth_seed
    del bpy.types.Scene.hair_growth_result_object
    del bpy.types.Scene.hair_growth_weight_threshold
    del bpy.types.Scene.hair_growth_weight_affects_length
    del bpy.types.Scene.hair_growth_length_weight_min
    del bpy.types.Scene.hair_growth_weight_affects_thickness
    del bpy.types.Scene.hair_growth_thickness_weight_min
    del bpy.types.Scene.hair_growth_tip_taper
    del bpy.types.Scene.hair_comb_radius
    del bpy.types.Scene.hair_comb_strength
    del bpy.types.Scene.hair_comb_pin_root
    del bpy.types.Scene.hair_style_apply_scope
    del bpy.types.Scene.hair_profile_kind
    del bpy.types.Scene.hair_profile_custom
    del bpy.types.Scene.hair_profile_segments
    del bpy.types.Scene.hair_profile_smooth
    del bpy.types.Scene.hair_profile_flat_arc_depth
    del bpy.types.Scene.hair_profile_flat_segments
    del bpy.types.Scene.hair_profile_clump_count
    del bpy.types.Scene.hair_profile_clump_spread
    del bpy.types.Scene.hair_profile_clump_strand_radius
    del bpy.types.Scene.hair_taper_mode
    del bpy.types.Scene.hair_thickness_scale
    del bpy.types.Scene.hair_mesh_reduction_ratio

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
