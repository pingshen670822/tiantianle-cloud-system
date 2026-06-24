# -*- coding: utf-8 -*-
import re
from pathlib import Path


TEXT_REPLACEMENTS = [
    ("California draw 18:30; safe update 18:50 PT. Taiwan is 09:50 during daylight time and 10:50 during standard time.", "加州當地晚上六點三十分開獎；加州時間晚上六點五十分後可安全更新。台灣夏令時間為早上九點五十分，冬令時間為早上十點五十分。"),
    ("consensus_latest:cache:lotterynet+lotteryusa+lotto8", "多來源一致：快取資料（樂透網、樂透美國、樂透八）"),
    ("Top9-only ultra precision second pass; no Top10-15 high confidence promotion", "只使用前九名核心二次精算；第十至十五名不得升為高信心"),
    ("strong_single_official_disabled_until_monthly_rate_reaches_20_percent", "強獨月度通過率未達二成前禁止正式發布"),
    ("three_hit_two_official_disabled_until_real_three_hit_two_samples_pass", "三碼組未通過實戰樣本前禁止正式發布"),
    ("five_hit_two_and_nine_hit_three_watch_only_until_monthly_and_360_walk_forward_pass", "五碼與九碼須等月度與三百六十期滾動回測通過前維持觀察"),
    ("two_hit_one_kept_as_relative_observation_not_official_high_probability", "二碼組只列相對觀察，不列正式高機率"),
    ("monthly_failed_numbers_soft_penalty_and_late_hit_recovery_promoted", "本月落空號軟降權，後段命中回收提高"),
    ("three_fold_conditional_lift_with_fdr", "三段條件提升與偽發現率檢定"),
    ("monthly_precision_guard", "月度精準守門"),
    ("blocked_low_maturity", "成熟度不足"),
    ("research_prediction", "研究預測"),
    ("research_only", "研究觀察"),
    ("usable_watch", "可觀察"),
    ("strict_downshift", "嚴格降級"),
    ("watch_only", "觀察中"),
    ("bayesian_posterior", "貝氏後驗"),
    ("cross_consensus", "交叉共識"),
    ("cycle_timing", "週期時點"),
    ("distribution_balance", "分布平衡"),
    ("ewma_fast", "快速趨勢"),
    ("ewma_slow", "慢速趨勢"),
    ("freq_300", "三百期頻率"),
    ("freq_100", "一百期頻率"),
    ("freq_50", "五十期頻率"),
    ("freq_20", "二十期頻率"),
    ("freq_10", "十期頻率"),
    ("freq_5", "五期頻率"),
    ("markov_chain", "馬可夫鏈"),
    ("missed_hit_recovery", "漏命中回收"),
    ("monte_carlo_stability", "蒙地卡羅穩定"),
    ("neural_network", "神經網路"),
    ("strong_single", "強獨"),
    ("two_hit_one", "二中一"),
    ("three_hit_two", "三中二"),
    ("five_hit_two", "五中二"),
    ("nine_hit_three", "九中三"),
    ("legacy_three_hit_one", "舊三碼組"),
    ("paircover", "對子覆蓋"),
    ("dedicated", "專用策略"),
    ("top_rank", "排名優先"),
    ("stability", "穩定策略"),
    ("neighbor", "鄰近號"),
    ("omission", "遺漏值"),
    ("pair", "共現對子"),
    ("date", "日期特徵"),
    ("Top10-15", "第十至十五名"),
    ("Top1-5", "第一至五名"),
    ("Top6-9", "第六至九名"),
    ("Top24", "前二十四名"),
    ("Top15", "前十五名"),
    ("Top12", "前十二名"),
    ("Top10", "前十名"),
    ("Top9", "前九名"),
    ("Top5", "前五名"),
    ("FDR", "偽發現率"),
    ("KPI", "關鍵指標"),
    ("lotterynet", "樂透網"),
    ("lotteryusa", "樂透美國"),
    ("lottolyzer", "樂透分析網"),
    ("lotto8", "樂透八"),
]

WORD_REPLACEMENTS = {
    "passed": "通過",
    "watch": "觀察",
    "warning": "警示",
    "official": "正式",
    "released": "已發布",
    "fresh": "已更新",
    "status": "狀態",
    "source": "來源",
    "cache": "快取",
    "latest": "最新",
    "draw": "開獎",
    "edge": "優勢值",
    "True": "是",
    "False": "否",
    "ok_before_draw": "開獎前正常",
    "ok": "正常",
}


def localize_plain_text(text):
    if not text:
        return text
    result = str(text)
    for source, target in TEXT_REPLACEMENTS:
        result = result.replace(source, target)
    for source, target in WORD_REPLACEMENTS.items():
        result = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(source)}(?![A-Za-z0-9_])", target, result)
    return result


def localize_visible_html(html_text):
    if not html_text:
        return html_text
    parts = re.split(r"(<[^>]+>)", str(html_text))
    output = []
    skip_text = False
    for part in parts:
        if not part:
            continue
        if part.startswith("<") and part.endswith(">"):
            lowered = part.lower()
            if lowered.startswith("<script"):
                skip_text = True
            output.append(part)
            if lowered.startswith("</script"):
                skip_text = False
            elif lowered.startswith("<style"):
                skip_text = True
            elif lowered.startswith("</style"):
                skip_text = False
        else:
            output.append(part if skip_text else localize_plain_text(part))
    return "".join(output)


def write_alias(path, alias_name):
    source = Path(path)
    if not source.exists():
        return None
    target = source.with_name(alias_name)
    target.write_bytes(source.read_bytes())
    return target

