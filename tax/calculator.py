"""
確定申告 税額計算モジュール（フリーランス・個人事業主向け）

対応する控除:
  - 基礎控除       : 480,000円（合計所得2,400万円以下）
  - 青色申告特別控除: 650,000円（e-Tax電子申告 + 複式簿記）または 100,000円（簡易簿記）

所得税率（令和6年以降）:
  課税所得          税率  控除額
  〜 1,950,000     5%       0
  〜 3,300,000    10%   97,500
  〜 6,950,000    20%  427,500
  〜 9,000,000    23%  636,000
  〜18,000,000    33% 1,536,000
  〜40,000,000    40% 2,796,000
    40,000,000〜  45% 4,796,000

復興特別所得税: 所得税額 × 2.102%
住民税: 課税所得 × 10%（均等割 5,000円は簡略化のため別途）
"""

from dataclasses import dataclass


# ── 定数 ────────────────────────────────────────────────────────────

INCOME_TAX_BRACKETS = [
    (1_950_000,  0.05,        0),
    (3_300_000,  0.10,   97_500),
    (6_950_000,  0.20,  427_500),
    (9_000_000,  0.23,  636_000),
    (18_000_000, 0.33, 1_536_000),
    (40_000_000, 0.40, 2_796_000),
    (float("inf"), 0.45, 4_796_000),
]

RECONSTRUCTION_TAX_RATE = 0.02102  # 復興特別所得税
RESIDENT_TAX_RATE = 0.10           # 住民税（所得割）
BASIC_DEDUCTION = 480_000          # 基礎控除
BLUE_RETURN_DEDUCTION_FULL = 650_000   # 青色申告特別控除（電子申告）
BLUE_RETURN_DEDUCTION_SIMPLE = 100_000  # 青色申告特別控除（簡易簿記）

INCOME_CATEGORIES = [
    "フリーランス収入",
    "SNS収益（広告・案件）",
    "コンサルティング収入",
    "アフィリエイト収入",
    "講演・セミナー収入",
    "その他収入",
]

EXPENSE_CATEGORIES = [
    "通信費",
    "広告宣伝費",
    "書籍・資料費",
    "セミナー・研修費",
    "機材・備品費",
    "ソフトウェア・サービス費",
    "交通費",
    "接待交際費",
    "外注費",
    "その他経費",
]


# ── データクラス ─────────────────────────────────────────────────────

@dataclass
class TaxResult:
    year: int
    total_income: int
    total_expense: int
    gross_profit: int           # 事業所得 = 収入 - 経費
    blue_return_deduction: int  # 青色申告特別控除
    basic_deduction: int        # 基礎控除
    taxable_income: int         # 課税所得
    income_tax: int             # 所得税
    reconstruction_tax: int     # 復興特別所得税
    resident_tax: int           # 住民税（所得割）
    total_tax: int              # 合計税額
    effective_rate: float       # 実効税率（%）


# ── 計算関数 ─────────────────────────────────────────────────────────

def calc_income_tax(taxable_income: int) -> int:
    """課税所得から所得税額を計算する"""
    if taxable_income <= 0:
        return 0
    for upper, rate, deduction in INCOME_TAX_BRACKETS:
        if taxable_income <= upper:
            return max(0, int(taxable_income * rate) - deduction)
    # 最高税率（上記ループで必ずヒットするが念のため）
    return max(0, int(taxable_income * 0.45) - 4_796_000)


def calculate(
    year: int,
    total_income: int,
    total_expense: int,
    use_blue_return: bool = True,
    blue_return_full: bool = True,
) -> TaxResult:
    """
    確定申告の税額を試算する。

    Args:
        year           : 対象年
        total_income   : 年間総収入（円）
        total_expense  : 年間総経費（円）
        use_blue_return: 青色申告を使うか
        blue_return_full: True=電子申告65万控除 / False=簡易簿記10万控除
    """
    gross_profit = max(0, total_income - total_expense)

    # 青色申告特別控除
    if use_blue_return:
        blue_deduction = BLUE_RETURN_DEDUCTION_FULL if blue_return_full else BLUE_RETURN_DEDUCTION_SIMPLE
    else:
        blue_deduction = 0
    blue_deduction = min(blue_deduction, gross_profit)  # 所得を超えない

    after_blue = max(0, gross_profit - blue_deduction)

    # 基礎控除（合計所得2,400万円以下で一律48万円。簡略化として常時適用）
    basic = min(BASIC_DEDUCTION, after_blue)
    taxable_income = max(0, after_blue - basic)

    income_tax = calc_income_tax(taxable_income)
    reconstruction_tax = int(income_tax * RECONSTRUCTION_TAX_RATE)
    resident_tax = int(taxable_income * RESIDENT_TAX_RATE)
    total_tax = income_tax + reconstruction_tax + resident_tax

    effective_rate = (total_tax / total_income * 100) if total_income > 0 else 0.0

    return TaxResult(
        year=year,
        total_income=total_income,
        total_expense=total_expense,
        gross_profit=gross_profit,
        blue_return_deduction=blue_deduction,
        basic_deduction=basic,
        taxable_income=taxable_income,
        income_tax=income_tax,
        reconstruction_tax=reconstruction_tax,
        resident_tax=resident_tax,
        total_tax=total_tax,
        effective_rate=effective_rate,
    )
