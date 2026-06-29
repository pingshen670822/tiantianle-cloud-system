import json
from pathlib import Path

ROOT = Path.cwd()
TEXT_REPLACEMENTS = {
    'industrial_fast_daily_full_history_v20260629': '每日快速全歷史引擎第20260629版',
    'verified_research_complete': '研究觀察通過',
    'fast_daily_recomputed': '每日快速重算完成',
    'deferred_fast_daily': '每日快速版延後深度回測',
    'watch_only': '觀察中',
    'official': '正式',
    'daily_5_39_current_precision_stability': '天天樂每日精準穩定模型',
    'daily_5_39': '天天樂每日模型',
    'Top 15': '前十五名',
    'Top15': '前十五',
    'Top10': '前十',
    'Top9': '前九',
    'Top5': '前五',
    'edge': '優勢值',
    'complete': '完整',
    'fast daily mode': '每日快速模式',
}

def clean_text(text):
    for old, new in TEXT_REPLACEMENTS.items():
        text = text.replace(old, new)
    return text

def clean_json_value(value):
    if isinstance(value, dict):
        return {key: clean_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_json_value(item) for item in value]
    if isinstance(value, str):
        return clean_text(value)
    return value

text_suffixes = {'.html', '.md', '.txt', '.webmanifest'}
for folder in [ROOT / 'reports', ROOT / 'site']:
    if not folder.exists():
        continue
    for path in folder.rglob('*'):
        if not path.is_file():
            continue
        if path.suffix.lower() in text_suffixes:
            data = path.read_text(encoding='utf-8')
            cleaned = clean_text(data)
            if cleaned != data:
                path.write_text(cleaned, encoding='utf-8')
        elif path.suffix.lower() == '.json':
            try:
                payload = json.loads(path.read_text(encoding='utf-8'))
            except Exception:
                continue
            cleaned_payload = clean_json_value(payload)
            if cleaned_payload != payload:
                path.write_text(json.dumps(cleaned_payload, ensure_ascii=False, indent=2), encoding='utf-8')
print('sanitized public outputs')
