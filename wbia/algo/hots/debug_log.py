"""Beautiful debug logging for the WBIA HotSpotter pipeline.

Usage: set the env var ``WBIA_DEBUG=1`` to enable.
    WBIA_DEBUG=1 python -m wbia --tf request_wbia_query_L0 ...
"""

from __future__ import annotations

import os

import numpy as np

_LOG_PATH = os.environ.get("WBIA_DEBUG_FILE", "/tmp/wbia-debug.log")


def _enabled() -> bool:
    return os.environ.get("WBIA_DEBUG", "0") == "1"


def _write_log(msg: str, *args: object) -> None:
    try:
        with open(_LOG_PATH, "a") as f:
            if args:
                f.write((msg % args) + "\n")
            else:
                f.write(msg + "\n")
            f.flush()
    except Exception:
        pass


# Write header on import
if _enabled():
    _write_log("")
    _write_log("─" * 72)
    _write_log("  WBIA HotSpotter Pipeline Debug Log")
    _write_log("─" * 72)
    _write_log("  log file: %s", _LOG_PATH)

SEP = "─" * 72
THIN = "·" * 48


def _pct(count: int, total: int) -> str:
    if total == 0:
        return "0.0%"
    return f"{100.0 * count / total:.1f}%"


def _stats(arr: np.ndarray) -> str:
    a = arr.flatten().astype(np.float64)
    return (
        f"min={np.min(a):.4f}  max={np.max(a):.4f}  "
        f"μ={np.mean(a):.4f}  σ={np.std(a):.4f}"
    )


# ── Stages ────────────────────────────────────────────────────────────


def stage_pipeline_start(qreq_) -> None:
    if not _enabled():
        return
    qp = qreq_.qparams
    _write_log("")
    _write_log("%s", SEP)
    _write_log("  WBIA HotSpotter Pipeline — vsmany")
    _write_log("%s", SEP)
    _write_log(
        "  K=%-2d  Kpad=dynamic  Knorm=%-2d  requery=%s", qp.K, qp.Knorm, qp.requery
    )
    _write_log(
        "  norm_rule=%s  sqrd_dist_on=%s  sv_on=%s",
        qp.normalizer_rule,
        qp.sqrd_dist_on,
        qp.sv_on,
    )
    _write_log("  score_method=%s", qp.score_method)


def stage_features(ibs, qreq_) -> None:
    if not _enabled():
        return
    qaids = qreq_.get_internal_qaids()
    daids = qreq_.get_internal_daids()
    _write_log("")
    _write_log("%s", SEP)
    _write_log("  STEP 1 — Feature Extraction")
    _write_log("%s", SEP)
    _write_log("  QUERIES: %d", len(qaids))
    for aid in qaids:
        vecs = ibs.get_annot_vecs(aid, config2_=qreq_.get_internal_query_config2())
        _write_log(
            "    qaid=%-5d  kp=%5d  desc=%s×%d",
            aid,
            len(vecs),
            vecs.shape,
            vecs.shape[1],
        )
    _write_log("  DATABASE: %d total", len(daids))
    _write_log("    (see STEP 2 for per-daid descriptor counts)")


def stage_impossible_filter(qreq_, impossible_daids_list, Kpad_list) -> None:
    if not _enabled():
        return
    _write_log("")
    _write_log("  %s", THIN)
    _write_log("  Self/Same-Name/Same-Image Filter Setup")
    _write_log("  %s", THIN)
    for i, qaid in enumerate(qreq_.get_internal_qaids()):
        imp = impossible_daids_list[i]
        _write_log(
            "  query[%d]  qaid=%-5d  impossible=%d  Kpad=%d",
            i,
            qaid,
            len(imp),
            Kpad_list[i],
        )


def stage_index_loaded(qreq_, nns_list) -> None:
    if not _enabled():
        return
    indexer = qreq_.indexer
    _write_log("")
    _write_log("%s", SEP)
    _write_log("  STEP 2 — Global FLANN Index")
    _write_log("%s", SEP)
    _write_log("  total descriptors  %d", indexer.num_indexed)
    _write_log("  index dtype        %s", indexer.idx2_vec.dtype)
    _write_log("  max_distance_sqrd  %s", indexer.max_distance_sqrd)
    for i, nns in enumerate(nns_list):
        nn_shape = (len(nns.qfx_list), nns.neighb_idxs.shape[1])
        _write_log(
            "  query[%d]  qaid=%-5d  nn_shape=(%d×%d)",
            i,
            nns.qaid,
            nn_shape[0],
            nn_shape[1],
        )


def stage_raw_dists(nns_list, sqrd_dist_on: bool) -> None:
    if not _enabled():
        return
    all_dists = np.concatenate([nns.neighb_dists.flatten() for nns in nns_list])
    _write_log("")
    _write_log("%s", SEP)
    _write_log("  STEP 3 — Raw FLANN Query Distances  (post-knn, pre-weighting)")
    _write_log("%s", SEP)
    _write_log("  sqrd_dist_on  %s", sqrd_dist_on)
    _write_log("  distances     %s", _stats(all_dists))
    for i, nns in enumerate(nns_list):
        d = nns.neighb_dists.flatten().astype(np.float64)
        _write_log("  query[%d]  qaid=%-5d  %s", i, nns.qaid, _stats(d))


def stage_dist_norm(nns_list) -> None:
    if not _enabled():
        return
    _write_log("")
    _write_log("  %s", THIN)
    _write_log("  Distance Normalization  ( / 524288 )")
    _write_log("  %s", THIN)
    for i, nns in enumerate(nns_list):
        d = nns.neighb_dists.flatten().astype(np.float64)
        _write_log("  query[%d]  qaid=%-5d  %s", i, nns.qaid, _stats(d))


def stage_voting_columns(nns_list, qreq_) -> None:
    if not _enabled():
        return
    K = qreq_.qparams.K
    Knorm = qreq_.qparams.Knorm
    _write_log("")
    _write_log("%s", SEP)
    _write_log("  Voting Columns  (K=%d + Kpad=dynamic, Knorm=%d)", K, Knorm)
    _write_log("%s", SEP)
    for i, nns in enumerate(nns_list):
        d = nns.neighb_dists
        voting = d[:, :K]
        normer_col = d[:, -Knorm:] if Knorm > 0 else d[:, -1:]
        _write_log("  query[%d]  qaid=%-5d", i, nns.qaid)
        _write_log(
            "           voting    %s  shape=(%d×%d)",
            _stats(voting),
            voting.shape[0],
            voting.shape[1],
        )
        _write_log("           normer    %s", _stats(normer_col))
        idxs = nns.neighb_idxs
        for j in range(min(K, idxs.shape[1])):
            col = idxs[:, j]
            valid = int((col >= 0).sum())
            total = col.shape[0]
            _write_log(
                "           col[%d]  valid=%d/%d (%s)",
                j,
                valid,
                total,
                _pct(valid, total),
            )


def stage_filter_counts(nns_list, nnvalid0_list, qreq_) -> None:
    if not _enabled():
        return
    _write_log("")
    _write_log("  %s", THIN)
    _write_log("  Baseline Neighbour Filter Results")
    _write_log("  %s", THIN)
    for i, (nns, valid) in enumerate(zip(nns_list, nnvalid0_list)):
        total = valid.size
        kept = int(valid.sum())
        _write_log(
            "  query[%d]  entries=%d  post-filter=%d  removed=%d (%s)",
            i,
            total,
            kept,
            total - kept,
            _pct(kept, total),
        )


def stage_active_filters(qreq_) -> None:
    if not _enabled():
        return
    config2_ = qreq_.extern_data_config2
    filters = []
    if config2_.lnbnn_on:
        filters.append("lnbnn" + ("_norm" if config2_.lnbnn_normer else ""))
    if config2_.bar_l2_on:
        filters.append("bar_l2")
    if config2_.fg_on:
        filters.append("fg")
    if config2_.ratio_thresh:
        filters.append("ratio")
    if config2_.const_on:
        filters.append("const")
    if config2_.normonly_on:
        filters.append("normonly")
    _write_log("")
    _write_log("%s", SEP)
    _write_log("  Active Filters")
    _write_log("%s", SEP)
    _write_log("  filters  %s", " × ".join(filters) if filters else "(none)")
    _write_log("  normalizer_rule  %s", qreq_.qparams.normalizer_rule)
    scorer = qreq_.lnbnn_normer
    _write_log(
        "  score_normalizer %s",
        scorer.__class__.__name__ if scorer is not None else "None",
    )
    if config2_.lnbnn_on and config2_.lnbnn_normer:
        _write_log("  lnbnn_norm_thresh  %s", config2_.lnbnn_norm_thresh)


def stage_weight_stats(filtkey_list, filtweights_list, filtvalids_list) -> None:
    if not _enabled():
        return
    _write_log("")
    _write_log("  %s", THIN)
    _write_log("  Per-Filter Weight Stats  (valid only)")
    _write_log("  %s", THIN)
    for fk_idx, fk in enumerate(filtkey_list):
        all_w = []
        n_valid_total = 0
        for qi, w in enumerate(filtweights_list):
            w2 = w[fk_idx]
            valid = filtvalids_list[qi][fk_idx]
            if valid is not None:
                w2 = w2[valid]
            all_w.append(w2.flatten())
            n_valid_total += len(w2.flatten())
        combined = np.concatenate(all_w) if all_w else np.array([])
        _write_log(
            "  %-12s  count=%d  %s",
            fk,
            n_valid_total,
            _stats(combined) if len(combined) > 0 else "(empty)",
        )


def stage_chipmatch_assembly(cm_list_FILT) -> None:
    if not _enabled():
        return
    _write_log("")
    _write_log("%s", SEP)
    _write_log("  STEP 7 — ChipMatch Assembly")
    _write_log("%s", SEP)
    for i, cm in enumerate(cm_list_FILT):
        n_annots = len(cm.daid_list)
        n_matches = sum(len(fm) for fm in cm.fm_list)
        n_filters = len(cm.fsv_col_lbls)
        _write_log(
            "  cm[%d]  qaid=%-5d  annots=%d  matches=%d  filters=%d",
            i,
            cm.qaid,
            n_annots,
            n_matches,
            n_filters,
        )


def stage_csum_scores(cm_list) -> None:
    if not _enabled():
        return
    _write_log("")
    _write_log("  %s", THIN)
    _write_log("  Per-Annotation csum Scores  (fsv.prod → sum)")
    _write_log("  %s", THIN)
    for cm in cm_list:
        if not hasattr(cm, "algo_annot_scores"):
            cm.evaluate_csum_annot_score()
        csum = cm.algo_annot_scores.get("csum")
        if csum is not None and len(csum) > 0:
            _write_log(
                "  qaid=%-5d  csum  count=%d  %s",
                cm.qaid,
                len(csum),
                _stats(np.array(csum)),
            )


def stage_spatial_verification(cm_list_SVER) -> None:
    if not _enabled():
        return
    _write_log("")
    _write_log("%s", SEP)
    _write_log("  STEP 8 — Spatial Verification")
    _write_log("%s", SEP)
    for cm in cm_list_SVER:
        n_annots = len(cm.daid_list)
        n_matches = sum(len(fm) for fm in cm.fm_list)
        _write_log(
            "  cm  qaid=%-5d  annots=%d  matches=%d", cm.qaid, n_annots, n_matches
        )


def stage_name_scores(qreq_, cm_list) -> None:
    if not _enabled():
        return
    score_method = qreq_.qparams.score_method
    _write_log("")
    _write_log("%s", SEP)
    _write_log("  STEP 9 — Name-Level Scoring  (%s)", score_method)
    _write_log("%s", SEP)
    for cm in cm_list:
        if score_method == "csum":
            maxcsum = (
                cm.algo_name_scores.get("maxcsum") if cm.algo_name_scores else None
            )
            if maxcsum is not None and len(maxcsum) > 0:
                _write_log(
                    "  qaid=%-5d  maxcsum  count=%d  %s",
                    cm.qaid,
                    len(maxcsum),
                    _stats(np.array(maxcsum)),
                )
        elif score_method == "nsum":
            nsum = cm.algo_name_scores.get("nsum") if cm.algo_name_scores else None
            if nsum is not None and len(nsum) > 0:
                _write_log(
                    "  qaid=%-5d  nsum  count=%d  %s",
                    cm.qaid,
                    len(nsum),
                    _stats(np.array(nsum)),
                )


def stage_final_ranking(qreq_, cm_list) -> None:
    if not _enabled():
        return
    score_method = qreq_.qparams.score_method
    _write_log("")
    _write_log("%s", SEP)
    _write_log("  STEP 10 — Final Ranking")
    _write_log("%s", SEP)
    _write_log("  %-4s  %-8s  %8s  %8s", "rank", "daid", "score", "matches")
    for cm in cm_list:
        _write_log("  ─── qaid=%d ───", cm.qaid)
        score_list = cm.score_list if hasattr(cm, "score_list") else np.array([])
        daid_list = cm.daid_list if hasattr(cm, "daid_list") else []
        n_matches_list = (
            [len(fm) for fm in cm.fm_list] if hasattr(cm, "fm_list") else []
        )
        if len(score_list) == 0:
            _write_log("    (no scores)")
            continue
        ranked = sorted(
            zip(daid_list, score_list, n_matches_list),
            key=lambda x: float(x[1]),
            reverse=True,
        )
        for rank, (daid, score, nm) in enumerate(ranked[:10], start=1):
            _write_log("  %4d  %-8d  %8.4f  %8d", rank, daid, float(score), nm)
