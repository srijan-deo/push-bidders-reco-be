with ranked as (
  select b.lot_nbr,
         l.lot_year,
         l.lot_make_cd,
         l.grp_model,
         l.acv,
         l.plug_lot_acv,
         l.repair_cost,
         l.yard_state_cd,
         l.sales_title_grp_desc,
         b.buyer_nbr,
         mbr_lic_type,
         f.mbr_state,
         bid_dttm, row_number() over (partition by b.lot_nbr order by b.bid_dttm desc) as rnk
  from `cprtpr-dataplatform-sp1.usviews.v_us_bids_fact` b
  join `cprtpr-dataplatform-sp1.usviews.v_us_lot_fact` l
    on b.lot_nbr = l.lot_nbr
    join `cprtpr-dataplatform-sp1`.usviews.v_us_member_fact f
    on b.buyer_nbr = f.mbr_nbr
    where mbr_country = 'USA'
            AND mbr_mbrshp_type_cd IN ('BASIC', 'PREMIER')
            AND mbr_site_status_cd = 'A'
            AND mbr_mbrshp_status_cd = 'A'
            AND mbr_lang_pref = 'en'
            AND mbr_status = 'A'
AND b.auc_dt = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
and lot_type_cd = 'V'
            and yard_country_cd = 'USA'
            and mbr_access_type not in ('BROKER', 'BRKBDR', 'MSTRBDR', 'MASTER')
)
select buyer_nbr,
       lot_nbr,
       lot_year,
       lot_make_cd,
       grp_model,
       acv,
       plug_lot_acv,
       repair_cost,
       yard_state_cd as lot_state,
       sales_title_grp_desc as lot_title,
       mbr_lic_type,
       bid_dttm,
       mbr_state
from ranked
where rnk = 2
