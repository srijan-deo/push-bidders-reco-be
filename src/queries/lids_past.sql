SELECT
    lot,
    JSON_EXTRACT(output_details_json, '$.fr.ext_dmg_scores.f_bmpr') AS frontRightBumperDamage,
    JSON_EXTRACT(output_details_json, '$.fr.ext_dmg_scores.f_dr') AS frontRightDoorDamage,
    JSON_EXTRACT(output_details_json, '$.fr.ext_dmg_scores.f_fndr') AS frontRightFenderDamage,
    JSON_EXTRACT(output_details_json, '$.fr.ext_dmg_scores.hdlght') AS frontRightHeadlightDamage,
    JSON_EXTRACT(output_details_json, '$.fr.ext_dmg_scores.hood') AS frontRightHoodDamage,
    JSON_EXTRACT(output_details_json, '$.fr.ext_dmg_scores.f_wndshld') AS frontRightWindshieldDamage,
    JSON_EXTRACT(output_details_json, '$.fr.ext_dmg_scores.whl') AS frontRightWheelDamage,
    JSON_EXTRACT(output_details_json, '$.fl.ext_dmg_scores.f_bmpr') AS frontLeftBumperDamage,
    JSON_EXTRACT(output_details_json, '$.fl.ext_dmg_scores.f_dr') AS frontLeftDoorDamage,
    JSON_EXTRACT(output_details_json, '$.fl.ext_dmg_scores.f_fndr') AS frontLeftFenderDamage,
    JSON_EXTRACT(output_details_json, '$.fl.ext_dmg_scores.hdlght') AS frontLeftHeadlightDamage,
    JSON_EXTRACT(output_details_json, '$.fl.ext_dmg_scores.hood') AS frontLeftHoodDamage,
    JSON_EXTRACT(output_details_json, '$.fl.ext_dmg_scores.f_wndshld') AS frontLeftWindshieldDamage,
    JSON_EXTRACT(output_details_json, '$.fl.ext_dmg_scores.whl') AS frontLeftWheelDamage,
    JSON_EXTRACT(output_details_json, '$.rr.ext_dmg_scores.r_bmpr') AS rearRightBumperDamage,
    JSON_EXTRACT(output_details_json, '$.rr.ext_dmg_scores.r_dr') AS rearRightDoorDamage,
    JSON_EXTRACT(output_details_json, '$.rr.ext_dmg_scores.r_qrtr_pnl') AS rearRightQuarterPanelDamage,
    JSON_EXTRACT(output_details_json, '$.rr.ext_dmg_scores.tllght') AS rearRightTaillightDamage,
    JSON_EXTRACT(output_details_json, '$.rr.ext_dmg_scores.r_wndshld') AS rearRightWindshieldDamage,
    JSON_EXTRACT(output_details_json, '$.rr.ext_dmg_scores.whl') AS rearRightWheelDamage,
    JSON_EXTRACT(output_details_json, '$.rr.ext_dmg_scores.trnk') AS rearRightTrunkDamage,
    JSON_EXTRACT(output_details_json, '$.rl.ext_dmg_scores.r_dr') AS rearLeftDoorDamage,
    JSON_EXTRACT(output_details_json, '$.rl.ext_dmg_scores.r_qrtr_pnl') AS rearLeftQuarterPanelDamage,
    JSON_EXTRACT(output_details_json, '$.rl.ext_dmg_scores.tllght') AS rearLeftTaillightDamage,
    JSON_EXTRACT(output_details_json, '$.rl.ext_dmg_scores.r_bmpr') AS rearLeftBumperDamage,
    JSON_EXTRACT(output_details_json, '$.rl.ext_dmg_scores.r_wndshld') AS rearLeftWindshieldDamage,
    JSON_EXTRACT(output_details_json, '$.rl.ext_dmg_scores.whl') AS rearLeftWheelDamage,
    JSON_EXTRACT(output_details_json, '$.rl.ext_dmg_scores.trnk') AS rearLeftTrunkDamage,
    GREATEST(
        JSON_EXTRACT(output_details_json, '$.fr.ext_dmg_scores.arbg_vsbl'),
        JSON_EXTRACT(output_details_json, '$.fl.ext_dmg_scores.arbg_vsbl'),
        JSON_EXTRACT(output_details_json, '$.rr.ext_dmg_scores.arbg_vsbl'),
        JSON_EXTRACT(output_details_json, '$.rl.ext_dmg_scores.arbg_vsbl')
    ) AS airbagsDeployedDetected,
    GREATEST(
        JSON_EXTRACT(output_details_json, '$.fr.ext_dmg_scores.spnsn_axl_dmg'),
        JSON_EXTRACT(output_details_json, '$.fl.ext_dmg_scores.spnsn_axl_dmg'),
        JSON_EXTRACT(output_details_json, '$.rr.ext_dmg_scores.spnsn_axl_dmg'),
        JSON_EXTRACT(output_details_json, '$.rl.ext_dmg_scores.spnsn_axl_dmg')
    ) AS suspensionOrAxleDetected,
    GREATEST(
        JSON_EXTRACT(output_details_json, '$.fr.ext_dmg_scores.dslctn'),
        JSON_EXTRACT(output_details_json, '$.fl.ext_dmg_scores.dslctn'),
        JSON_EXTRACT(output_details_json, '$.rr.ext_dmg_scores.dslctn'),
        JSON_EXTRACT(output_details_json, '$.rl.ext_dmg_scores.dslctn')
    ) AS dislocationDetected,
    GREATEST(
        JSON_EXTRACT(output_details_json, '$.fr.ext_dmg_scores.flt_tr'),
        JSON_EXTRACT(output_details_json, '$.fl.ext_dmg_scores.flt_tr'),
        JSON_EXTRACT(output_details_json, '$.rr.ext_dmg_scores.flt_tr'),
        JSON_EXTRACT(output_details_json, '$.rl.ext_dmg_scores.flt_tr')
    ) AS flatTireDetected,
    JSON_EXTRACT(output_details_json, '$.lids_version') AS lids_version
FROM `cprtpr-dataplatform-sp1`.usviews.v_us_lot_image_damage_scores_fact a1
    join (
    SELECT
        l.lot_nbr FROM `cprtpr-dataplatform-sp1`.usviews.v_us_lot_fact l
                join `cprtpr-dataplatform-sp1.usviews.v_us_bids_fact` b
                on l.lot_nbr = b.lot_nbr
where b.auc_dt = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
        AND lot_type_cd IN ('V')
        AND yard_country_cd = 'USA') lots
    on a1.lot = lots.lot_nbr
