import bpy

from .core import _active_curve_object, _is_hair_curve_object


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
        col.prop(scene, "hair_close_tips", text="Fechar pontas dos fios")
        col.prop(scene, "hair_root_embed_depth", text="Profundidade da raiz")

        row = layout.row(align=True)
        row.operator("hair.snap_active_mecha", text="Snap Raiz", icon='SNAP_FACE')

        layout.separator()
        comb_box = layout.box()
        comb_box.label(text="Ferramentas interativas")
        row = comb_box.row(align=True)
        row.operator("hair.create_mecha_brush", text="Criar (Clique)", icon='CURVE_BEZCURVE')
        row.operator("hair.comb_brush", text="Pentear", icon='SCULPTMODE_HLT')
        comb_box.prop(scene, "hair_comb_radius", text="Raio da escova (px)")
        comb_box.prop(scene, "hair_comb_strength", text="Força da escova")
        comb_box.prop(scene, "hair_comb_pin_root", text="Fixar raiz ao pentear")
        info_comb = comb_box.column(align=True)
        info_comb.scale_y = 0.8
        info_comb.label(text="Criar: S ajusta espessura só desta mecha (com preview)")
        info_comb.label(text="Espessura: clique esquerdo ou Enter confirma · Esc/Botão direito cancela")
        info_comb.label(text="Pentear: arraste penteia · Ctrl+arraste alisa")
        info_comb.label(text="Ambos: Ctrl+Z desfaz · Enter/Esc confirma/sai")

        active = _active_curve_object(context)
        if active is not None and _is_hair_curve_object(active) and active.get("hair_thickness_local_scale") is not None:
            local_row = layout.row(align=True)
            local_row.label(text=f"Espessura individual: {active['hair_thickness_local_scale']:.2f}", icon='MOD_THICKNESS')
            local_row.operator("hair.reset_local_thickness", text="", icon='X')

        layout.separator()
        grow_box = layout.box()
        grow_box.label(text="Crescimento pela pintura")
        target = scene.hair_surface_target
        if target is not None and target.type == 'MESH':
            grow_box.prop_search(scene, "hair_growth_vertex_group", target, "vertex_groups", text="Vertex Group")
        else:
            grow_box.prop(scene, "hair_growth_vertex_group", text="Vertex Group")
        grow_box.prop(scene, "hair_new_vertex_group_name", text="Novo Vertex Group")

        row = grow_box.row(align=True)
        row.operator("hair.create_vertex_group", text="Criar novo", icon='ADD')
        row.operator("hair.open_weight_paint", text="Editar vertex group", icon='MOD_VERTEX_WEIGHT')

        grow_box.operator("hair.apply_growth_from_paint", text="Aplicar", icon='FILE_REFRESH')

        grow_box.prop(scene, "hair_growth_count", text="Quantidade")

        guide_box = grow_box.box()
        guide_box.label(text="Guia (comprimento / elevação / ângulo)")
        guide_box.label(text="Usado no Crescimento pela pintura e na Criar (Clique)", icon='INFO')
        col = guide_box.column(align=True)
        col.prop(scene, "hair_guide_length", text="Comprimento")
        col.prop(scene, "hair_guide_lift", text="Elevação")
        col.prop(scene, "hair_guide_angle", text="Ângulo")
        col.prop(scene, "hair_guide_curve_amount", text="Curvatura")
        col.prop(scene, "hair_guide_tip_taper", text="Afinar ponta (mecha)")
        col.prop(scene, "hair_taper_mode", text="Afinação")

        live_row = guide_box.row(align=True)
        live_row.prop(scene, "hair_guide_live_update", text="Atualizar ao vivo")
        live_row.prop(scene, "hair_style_apply_scope", text="")
        guide_box.operator("hair.apply_guide_now", text="Aplicar Guia Agora", icon='FILE_REFRESH')
        info_guide = guide_box.column(align=True)
        info_guide.scale_y = 0.8
        info_guide.label(text="Reconstrói só fios já criados por 'Criar (Clique)' ou pintura")
        info_guide.label(text="A raiz de cada fio é mantida no lugar original")

        grow_box.prop(scene, "hair_growth_length_variation", text="Variação de tamanho")
        grow_box.prop(scene, "hair_growth_angle_variation", text="Variação de direção")
        grow_box.prop(scene, "hair_growth_min_spacing", text="Espaçamento mínimo")
        grow_box.prop(scene, "hair_growth_spacing_attempts", text="Tentativas de espaço")
        grow_box.prop(scene, "hair_growth_mirror_other_side", text="Espelhar outro lado")
        grow_box.prop(scene, "hair_growth_fill_mode", text="Priorizar vazios")
        grow_box.prop(scene, "hair_growth_seed", text="Seed")

        coherence_col = grow_box.box()
        coherence_col.label(text="Coerência com a pintura", icon='WPAINT_HLT')
        coherence_col.prop(scene, "hair_growth_weight_threshold", text="Peso mínimo")
        coherence_col.prop(scene, "hair_growth_weight_affects_length", text="Peso afeta comprimento")
        if scene.hair_growth_weight_affects_length:
            coherence_col.prop(scene, "hair_growth_length_weight_min", text="Comprimento mínimo")
        coherence_col.prop(scene, "hair_growth_weight_affects_thickness", text="Peso afeta espessura")
        if scene.hair_growth_weight_affects_thickness:
            coherence_col.prop(scene, "hair_growth_thickness_weight_min", text="Espessura mínima")
        coherence_col.prop(scene, "hair_growth_tip_taper", text="Afinamento da ponta")

        layout.separator()
        box = layout.box()
        box.label(text="Estilização (perfil)")

        auto_row = box.row(align=True)
        auto_row.label(text="Auto-aplicar em:", icon='FILE_REFRESH')
        auto_row.prop(scene, "hair_style_apply_scope", text="")
        box.operator("hair.apply_style_now", text="Aplicar Agora (forçar)", icon='CHECKMARK')

        box.prop(scene, "hair_profile_kind", text="")
        if scene.hair_profile_kind == 'CLUMP':
            box.prop(scene, "hair_profile_clump_count", text="Fios no perfil")
            box.prop(scene, "hair_profile_clump_spread", text="Raio do feixe")
            box.prop(scene, "hair_profile_clump_strand_radius", text="Espessura de cada fio")
            box.prop(scene, "hair_profile_smooth", text="Suavizar cada fio")
        elif scene.hair_profile_kind == 'CUSTOM':
            row = box.row(align=True)
            row.prop(scene, "hair_profile_custom", text="Curva")
            row.operator("hair.normalize_custom_profile", text="", icon='FILE_REFRESH')
        elif scene.hair_profile_kind == 'ROUND':
            box.prop(scene, "hair_profile_segments", text="Lados")
            box.prop(scene, "hair_profile_smooth", text="Suavizar perfil")
        elif scene.hair_profile_kind == 'STAR':
            box.prop(scene, "hair_profile_smooth", text="Suavizar perfil")
        elif scene.hair_profile_kind == 'FLAT':
            box.prop(scene, "hair_profile_flat_arc_depth", text="Curvatura (arco)")
            box.prop(scene, "hair_profile_flat_segments", text="Segmentos do arco")
            box.prop(scene, "hair_profile_smooth", text="Suavizar arco")
        info_style = box.column(align=True)
        info_style.scale_y = 0.8
        info_style.label(text="Curvatura/segmentos/fios do tufo não são ao vivo:")
        info_style.label(text="use 'Aplicar Agora' após ajustar (evita objetos extras)")
        box.operator("hair.apply_profile", text="Aplicar à curva ativa")

        layout.separator()
        row = layout.row(align=True)
        row.prop(scene, "hair_thickness_scale", text="Espessura")
        row.operator("hair.set_thickness", text="", icon='FILE_REFRESH')

        layout.separator()
        dec_box = layout.box()
        dec_box.label(text="Redução ao converter")
        dec_box.prop(scene, "hair_mesh_reduction_ratio", text="Preservação", slider=True)
        dec_box.operator("hair.convert_active_to_light_mesh", text="Converter curva ativa para Mesh leve")

        layout.separator()
        info = layout.box()
        info.label(text="Fluxo:")
        info.label(text="1. Escolha a cabeça acima")
        info.label(text="2. Use 'Criar (Clique)' para as guias")
        info.label(text="3. Clique em Editar vertex group e pinte o couro cabeludo")
        info.label(text="4. Clique em Aplicar para gerar ou recriar o crescimento")
        info.label(text="5. Use a Escova para pentear e ajustar as mechas")
