# -*- coding: utf-8 -*-
"""
組織適正化シミュレーター — Production v2.0
"""

import streamlit as st
import streamlit.components.v1 as components  # Google翻訳ブロック用
from pathlib import Path
from datetime import date
import time
from io import BytesIO

try:
    import stripe as _stripe
    _STRIPE_AVAILABLE = True
except ImportError:
    _stripe = None
    _STRIPE_AVAILABLE = False

# ─────────────────────────────────────────────
#  アプリルートディレクトリ（絶対パス不使用）
# ─────────────────────────────────────────────
_APP_DIR = Path(__file__).parent

# ─────────────────────────────────────────────
#  ページ設定
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="算命学 組織適正・相性診断｜プロフェッショナル鑑定レポート",
    page_icon="📊",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────
#  Google翻訳ポップアップ完全ブロック + SEO
#
#  ※ st.markdown の <script> は Streamlit の子 iframe 内で動作するため
#    window.parent.document を使わないとトップの <html lang> に届かない。
#    st.components.v1.html を用いて親フレームを直接操作する。
# ─────────────────────────────────────────────
components.html("""
<script>
(function(){
  try {
    var root = window.parent.document.documentElement;
    var h    = window.parent.document.head;

    // 1) lang="ja" + translate="no" を即座にトップフレームへ反映
    root.setAttribute('lang', 'ja');
    root.setAttribute('translate', 'no');

    // 2) Streamlit が lang を 'en' へ上書きするのを MutationObserver で監視・復元
    new MutationObserver(function(muts){
      muts.forEach(function(m){
        if (m.attributeName === 'lang' && root.getAttribute('lang') !== 'ja')
          root.setAttribute('lang', 'ja');
      });
    }).observe(root, { attributes: true, attributeFilter: ['lang'] });

    // 3) <meta name="google" content="notranslate">（重複防止）
    if (!window.parent.document.querySelector('meta[name="google"][content="notranslate"]')) {
      var nt = window.parent.document.createElement('meta');
      nt.name = 'google'; nt.content = 'notranslate'; h.appendChild(nt);
    }

    // 4) <meta http-equiv="content-language" content="ja">（Chrome向け）
    if (!window.parent.document.querySelector('meta[http-equiv="content-language"]')) {
      var cl = window.parent.document.createElement('meta');
      cl.setAttribute('http-equiv', 'content-language'); cl.content = 'ja'; h.appendChild(cl);
    }

    // 5) SEO メタディスクリプション
    if (!window.parent.document.querySelector('meta[name="description"]')) {
      var md = window.parent.document.createElement('meta');
      md.name = 'description';
      md.content = '算命学の知恵を現代の組織戦略に。個人の資質とチームの相性を可視化し、離職防止や生産性向上を支援する診断ツールです。';
      h.appendChild(md);
    }

    // 6) JSON-LD 構造化データ
    if (!window.parent.document.querySelector('script[type="application/ld+json"]')) {
      var ld = window.parent.document.createElement('script');
      ld.type = 'application/ld+json';
      ld.text = JSON.stringify({
        "@context":"https://schema.org","@type":"SoftwareApplication",
        "name":"算命学 組織適正・相性診断",
        "description":"算命学の知恵を現代の組織戦略に。個人の資質とチームの相性を可視化し、離職防止や生産性向上を支援する診断ツールです。",
        "applicationCategory":"BusinessApplication","operatingSystem":"Web",
        "offers":{"@type":"Offer","price":"0","priceCurrency":"JPY","description":"基本診断は無料。完全版PDFレポートは有料。"},
        "keywords":"算命学,組織診断,適性診断,相性診断,離職防止,生産性向上,マネジメント,帝王学"
      });
      h.appendChild(ld);
    }
  } catch(e) { /* クロスオリジン制約等の例外を無視 */ }
})();
</script>
""", height=0)

# ─────────────────────────────────────────────
#  決済設定（Stripe）
#
#  .streamlit/secrets.toml に以下を記述（git ignore 必須）:
#    STRIPE_SECRET_KEY      = "sk_test_..."
#    STRIPE_PRICE_PERSONAL  = "price_xxxxxx"   # ¥980
#    STRIPE_PRICE_BUSINESS  = "price_xxxxxx"   # ¥1,480
#    BASE_URL               = "http://localhost:8501"  # 本番は https://your-app.streamlit.app
# ─────────────────────────────────────────────
def _get_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return default

_STRIPE_SK   = _get_secret("STRIPE_SECRET_KEY")
_PRICE_P1    = _get_secret("STRIPE_PRICE_PERSONAL", "price_xxxxxx")
_PRICE_BUSI  = _get_secret("STRIPE_PRICE_BUSINESS", "price_xxxxxx")
_BASE_URL    = _get_secret("BASE_URL", "http://localhost:8501")

# SK が取得できていれば Stripe を有効化（価格 ID が未設定でも API 呼び出し時にエラーで通知）
_STRIPE_READY = _STRIPE_AVAILABLE and bool(_STRIPE_SK)


def _create_checkout_session(
    price_id: str,
    product_key: str,
    name: str = "",
    birth_str: str = "",
) -> str | None:
    """Stripe Checkout セッションを作成し、決済ページ URL を返す。失敗時は None。
    name / birth_str を metadata に保存することで、決済完了後の戻り時にセッション状態を復元できる。
    birth_str フォーマット:
      個人分析  → "YYYY-MM-DD"
      組織相性  → "YYYY-MM-DD|YYYY-MM-DD"（A|B の順）
    """
    if not _STRIPE_READY:
        return None
    try:
        _stripe.api_key = _STRIPE_SK
        session = _stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="payment",
            # ?status=success を検知して決済完了と判断する
            # session_id も付けることで Stripe API で検証可能（改ざん対策）
            success_url=(
                f"{_BASE_URL}"
                f"?status=success"
                f"&session_id={{CHECKOUT_SESSION_ID}}"
                f"&product={product_key}"
            ),
            cancel_url=_BASE_URL,
            metadata={
                "product":   product_key,
                "name":      name[:490],        # Stripe metadata 値は 500 文字以内
                "birth":     birth_str[:490],
            },
        )
        return session.url
    except Exception as _e:
        st.error(f"Stripe エラー: {_e}")
        return None


@st.cache_data(ttl=600, show_spinner=False)
def _retrieve_stripe_metadata(session_id: str) -> dict | None:
    """Stripe セッション ID を検証し、payment_status == 'paid' なら metadata dict を返す。
    キャッシュ TTL=10分。同一 session_id への重複 API 呼び出しを防ぐ。
    """
    if not _STRIPE_READY:
        return None
    try:
        _stripe.api_key = _STRIPE_SK
        session = _stripe.checkout.Session.retrieve(session_id)
        if session.payment_status == "paid":
            return dict(session.metadata or {})
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────
#  辞書データ（固定テキスト）
# ─────────────────────────────────────────────
STAR_PROFILE = {
    "貫索星": "独立独歩のマイペース職人。自分の裁量で進められる業務で最も輝きます。",
    "石門星": "フラットな視点を持つチームの調整役。人間関係を円滑にする天才です。",
    "鳳閣星": "自然体で客観的な表現者。プレッシャーのない環境で的確な発信力を持ちます。",
    "調舒星": "独自の美学を持つ完璧主義のアーティスト。一人で没頭できる専門分野で無双します。",
    "禄存星": "愛情と魅力にあふれるカリスマ。人を惹きつけ、大型案件を獲ってくる歩くパワースポットです。",
    "司禄星": "堅実で慎重な蓄積のプロ。絶対にミスをしない、組織の頼れるバックオフィスです。",
    "車騎星": "考えるより先に動く特攻隊長。スピード感のある短期決戦で圧倒的な成果を出します。",
    "牽牛星": "責任感と自尊心の塊。ルールとメンツを重んじる、組織の完璧なエリートです。",
    "龍高星": "ルール破壊の異端児。ルーティンを嫌い、ゼロから新しい事業を生み出す天才です。",
    "玉堂星": "論理と伝統を重んじる知性派。過去のデータや理屈から最適解を導き出します。",
}

COMPATIBILITY_LOGIC = {
    "same": {
        "title": "【似た者同士・鏡の相性】",
        "text": (
            "仕事に対する根底の価値観が同じなので、ツーカーの「阿吽の呼吸」で仕事が進みます。"
            "ただし、お互いの弱点も同じになるため、同じミスを連発しないよう第三者のチェックが必要です。"
        ),
    },
    "different": {
        "title": "【水と油・補完の相性】",
        "text": (
            "ビジネスの進め方が全く異なる「異星人」同士です。"
            "相手を自分のやり方にハメようとすると反発が起きます。"
            "しかし、得意領域を完全に「分業」した瞬間、弱点をカバーし合う最強のチームに化けます。"
        ),
    },
}


# ─────────────────────────────────────────────
#  計算エンジン
#
#  【五徳の位置と算出元】
#    頭  = 年干         の星（対 日干）
#    左手 = 月支の正気蔵干 の星（対 日干）
#    中央 = 日支の正気蔵干 の星（対 日干）← 中心星
#    右手 = 年支の正気蔵干 の星（対 日干）
#    足  = 月干         の星（対 日干）
#
#  バリデーション済み（1994-01-21 = 丁未日）:
#    頭=車騎星, 左手=鳳閣星, 中央=鳳閣星, 右手=禄存星, 足=龍高星 ✓
# ─────────────────────────────────────────────

STEMS    = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
BRANCHES = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

_ELEM  = [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]  # 0=木 1=火 2=土 3=金 4=水
_POL   = [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]  # 0=陽 1=陰
_GEN   = [1, 2, 3, 4, 0]                  # 相生（木→火→土→金→水→木）
_CTRL  = [2, 3, 4, 0, 1]                  # 相克（木→土→水→火→金→木）

# 各地支の正気蔵干（主気）インデックス
# 子=癸, 丑=己, 寅=甲, 卯=乙, 辰=戊, 巳=丙, 午=丁, 未=己, 申=庚, 酉=辛, 戌=戊, 亥=壬
_HIDDEN = [9, 5, 0, 1, 4, 2, 3, 5, 6, 7, 4, 8]

# 月干起算（寅月の天干）: 甲己年=丙, 乙庚年=戊, 丙辛年=庚, 丁壬年=壬, 戊癸年=甲
_MONTH_STEM_START = [2, 4, 6, 8, 0]

# 節気（固定近似値）: (月, 日, 月支インデックス)
_SOLAR_TERMS = [
    (1, 6, 1), (2, 4, 2), (3, 6, 3),  (4, 5, 4),
    (5, 6, 5), (6, 6, 6), (7, 7, 7),  (8, 7, 8),
    (9, 8, 9), (10, 8, 10), (11, 7, 11), (12, 7, 0),
]

POSITION_LABELS = {
    "head":   "頭",
    "left":   "左手",
    "center": "中央",
    "right":  "右手",
    "feet":   "足",
}


# ── ユリウス通日 ──────────────────────────────
def _jdn(d: date) -> int:
    a = (14 - d.month) // 12
    y = d.year + 4800 - a
    m = d.month + 12 * a - 3
    return d.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045

_REF_JDN = _jdn(date(1900, 1, 1))  # 甲戌日（日干=甲=0, 日支=戌=10）


# ── 中国年（立春 2/4 で切り替え）────────────────
def _cy(d: date) -> int:
    return d.year if d >= date(d.year, 2, 4) else d.year - 1


# ── 各柱インデックス ──────────────────────────
def year_stem_idx(d: date) -> int:
    return (_cy(d) - 4) % 10

def year_branch_idx(d: date) -> int:
    return (_cy(d) - 4) % 12

def month_branch_idx(d: date) -> int:
    br = 0  # 大雪前（1月上旬）は子月
    for m, dy, b in _SOLAR_TERMS:
        if d >= date(d.year, m, dy):
            br = b
    return br

def month_stem_idx(d: date) -> int:
    ys = year_stem_idx(d)
    mb = month_branch_idx(d)
    offset = (mb - 2 + 12) % 12
    return (_MONTH_STEM_START[ys % 5] + offset) % 10

def day_stem_idx(d: date) -> int:
    return (_jdn(d) - _REF_JDN) % 10

def day_branch_idx(d: date) -> int:
    # オフセット=10: 1900-01-01=甲戌日（戌=10）を基準に実測検証済み
    return (_jdn(d) - _REF_JDN + 10) % 12


# ── 星の計算（天干インデックス → 日干との関係） ─────
def calc_star(stem_idx: int, day_stem_idx: int) -> str:
    ye, de = _ELEM[stem_idx], _ELEM[day_stem_idx]
    yp, dp = _POL[stem_idx],  _POL[day_stem_idx]
    sp = (yp == dp)
    if ye == de:              return "貫索星" if sp else "石門星"   # 比肩 / 劫財
    if _GEN[de]  == ye:       return "鳳閣星" if sp else "調舒星"   # 食神 / 傷官
    if _CTRL[de] == ye:       return "禄存星" if sp else "司禄星"   # 偏財 / 正財
    if _GEN[ye]  == de:       return "龍高星" if sp else "玉堂星"   # 偏印 / 印綬
    if _CTRL[ye] == de:       return "車騎星" if sp else "牽牛星"   # 偏官 / 正官
    return "未定義"


# ── 五徳（5ポジション）の計算 ──────────────────
def calc_gototoku(birth: date) -> dict:
    """
    五徳と柱情報を辞書で返す。

    Returns
    -------
    dict with keys:
      head, left, center, right, feet  : 各位置の星名
      day_pillar, year_pillar, month_pillar : '丁未' 形式の文字列
      ds, db : 日干/日支インデックス
    """
    ds = day_stem_idx(birth)
    db = day_branch_idx(birth)
    ys = year_stem_idx(birth)
    yb = year_branch_idx(birth)
    ms = month_stem_idx(birth)
    mb = month_branch_idx(birth)

    return {
        "head":         calc_star(ys,          ds),   # 年干
        "left":         calc_star(_HIDDEN[mb], ds),   # 月支蔵干
        "center":       calc_star(_HIDDEN[db], ds),   # 日支蔵干（中心星）
        "right":        calc_star(_HIDDEN[yb], ds),   # 年支蔵干
        "feet":         calc_star(ms,          ds),   # 月干
        "day_pillar":   STEMS[ds] + BRANCHES[db],
        "year_pillar":  STEMS[ys] + BRANCHES[yb],
        "month_pillar": STEMS[ms] + BRANCHES[mb],
        "ds": ds, "db": db,
    }


# ─────────────────────────────────────────────
#  天中殺の計算
# ─────────────────────────────────────────────
_KANSHI_BASE = [
    "甲子","乙丑","丙寅","丁卯","戊辰","己巳","庚午","辛未","壬申","癸酉",
    "甲戌","乙亥","丙子","丁丑","戊寅","己卯","庚辰","辛巳","壬午","癸未",
    "甲申","乙酉","丙戌","丁亥","戊子","己丑","庚寅","辛卯","壬辰","癸巳",
    "甲午","乙未","丙申","丁酉","戊戌","己亥","庚子","辛丑","壬寅","癸卯",
    "甲辰","乙巳","丙午","丁未","戊申","己酉","庚戌","辛亥","壬子","癸丑",
    "甲寅","乙卯","丙辰","丁巳","戊午","己未","庚申","辛酉","壬戌","癸亥",
]
_TENCHU_GROUPS = ["戌亥", "申酉", "午未", "辰巳", "寅卯", "子丑"]

def get_tenchusatsu(day_pillar: str) -> str:
    if day_pillar in _KANSHI_BASE:
        return _TENCHU_GROUPS[_KANSHI_BASE.index(day_pillar) // 10]
    return "不明"


# ─────────────────────────────────────────────
#  PDF用スターデータ（個人向け B2C）
# ─────────────────────────────────────────────
STAR_DATA_PERSONAL = {
    "貫索星": {"desc": "独立独歩のマイペース。自分のやり方を守りたい職人気質です。",
               "strategy": "人に合わせすぎず、自分の裁量で進められる単独業務や専門職で最も輝きます。"},
    "石門星": {"desc": "フラットな視点を持つ協調性の星。人間関係を円滑にする天才です。",
               "strategy": "チームワークを活かせる環境や、人と人を繋ぐ調整役・サポート役として重宝されます。"},
    "鳳閣星": {"desc": "自然体でマイペースな表現者。のんびり楽しむことが一番のエネルギー源です。",
               "strategy": "ガチガチのノルマを避け、発信力や客観的視点を活かせる風通しの良い環境がベストです。"},
    "調舒星": {"desc": "繊細な感性と独自の美学を持つアーティスト。孤独と完璧を愛します。",
               "strategy": "一人の時間を確保し、クリエイティブな仕事や専門分野に没頭すると才能が開花します。"},
    "禄存星": {"desc": "愛情深く、人から感謝されたい奉仕家。息をするように人に好かれるパワースポットです。",
               "strategy": "「誰かのために」動くことで評価される営業やサービス業などで圧倒的な結果を出します。"},
    "司禄星": {"desc": "堅実で慎重な蓄積のプロ。ルーティンと平和を愛する常識人です。",
               "strategy": "突発的な変更が少ない環境で、事務や管理などコツコツ積み上げる業務で絶大な信頼を得ます。"},
    "車騎星": {"desc": "考えるより先に動くスピードスター。白黒ハッキリさせたい特攻隊長です。",
               "strategy": "長い会議はNG。短期決戦で結果が見える営業や、体を動かす現場仕事で無双します。"},
    "牽牛星": {"desc": "責任感と自尊心の塊。ルールを重んじる完璧な優等生（社畜プロ）です。",
               "strategy": "明確な「役職」や「評価」がもらえる環境で、管理部門や公的な仕事に強い適性があります。"},
    "龍高星": {"desc": "束縛を嫌い、常に新しい刺激を求める改革の異端児。ルーティンが死ぬほど苦手です。",
               "strategy": "無意味な社内ルールを避け、企画や新規事業など「ゼロからイチを生み出す」環境へ！"},
    "玉堂星": {"desc": "論理的思考と伝統を重んじる知性派。過去のデータから学ぶ優得生です。",
               "strategy": "感情論ではなく、データや理屈が通る環境（研究、教育、分析など）で才能を発揮します。"},
}

# ─────────────────────────────────────────────
#  PDF用スターデータ（組織相性 B2B）
# ─────────────────────────────────────────────
STAR_DATA_BUSINESS = {
    "貫索星": {"desc": "自分のペースとやり方を絶対に崩さない、独立独歩の職人肌です。",
               "strategy": "細かく管理・干渉せず、裁量と目標だけを与えて任せきる。"},
    "石門星": {"desc": "上下関係よりも対等な繋がりと、チームの和を重んじる政治家タイプです。",
               "strategy": "上から目線での命令を避け、事前に「相談・根回し」を行って巻き込む。"},
    "鳳閣星": {"desc": "プロセスや楽しさを重視し、自然体で物事に取り組む自由人です。",
               "strategy": "ガチガチのノルマで縛らず、ゲーム感覚や自由度を持たせて働かせる。"},
    "調舒星": {"desc": "独特の美学と鋭い感性を持ち、完璧主義で傷つきやすい一面があります。",
               "strategy": "「あなたにしかできない」と特別感を伝え、細やかな感情に寄り添う。"},
    "禄存星": {"desc": "貢献したい・認められたいという「承認欲求」が非常に強い奉仕家です。",
               "strategy": "小さな成果でも「助かりました！」と大げさに感謝を伝え、承認欲求を満たす。"},
    "司禄星": {"desc": "着実な積み重ねと安全を重んじる、非常に堅実で保守的な性質です。",
               "strategy": "急な変更やサプライズを避け、データ・マニュアル・前例を提示して安心させる。"},
    "車騎星": {"desc": "考えるよりも先に体が動く、スピード重視の特攻隊長です。",
               "strategy": "言い訳や長い前置きは避け、とにかく「結論から」「スピーディーに」指示を出す。"},
    "牽牛星": {"desc": "礼儀作法やメンツ、ブランドを非常に大切にするプライドの高いエリート気質です。",
               "strategy": "人前で叱るなどの恥をかかせる行為は絶対NG。役職や立場を尊重し、礼儀を通す。"},
    "龍高星": {"desc": "ルーティンワークや古い規則を嫌う、自由奔放なアイデアマン・改革者です。",
               "strategy": "「今までこうだったから」という理屈は捨て、常に新しい挑戦やミッションを与える。"},
    "玉堂星": {"desc": "論理や伝統、知性を重んじる理論派です。感情論や気合は通じません。",
               "strategy": "客観的な事実や過去の実績に基づき、論理的に筋の通った説明で納得させる。"},
}

# ─────────────────────────────────────────────
#  組織相性PDF用：五行分析ヘルパー
# ─────────────────────────────────────────────
_ELEM_MAP  = {"貫索星":"木","石門星":"木","鳳閣星":"火","調舒星":"火",
              "禄存星":"土","司禄星":"土","車騎星":"金","牽牛星":"金",
              "龍高星":"水","玉堂星":"水"}
_SOUSEI    = [("木","火"),("火","土"),("土","金"),("金","水"),("水","木")]
_SOUKOKU   = [("木","土"),("土","水"),("水","火"),("火","金"),("金","木")]

def _power_balance(ca: str, cb: str, na: str, nb: str) -> str:
    ea, eb = _ELEM_MAP.get(ca,""), _ELEM_MAP.get(cb,"")
    if not ea or not eb: return "互いに独立したプロとして良い緊張感を持って働ける関係です。"
    if ea == eb: return "お二人の仕事の進め方は【同質】です。ツーカーで通じ合いますが、意見がぶつかると平行線になりやすいので、第三者の視点を入れるとスムーズです。"
    if (ea,eb) in _SOUSEI: return f"仕事のエネルギーが{na}様から{nb}様へ流れています。あなたがサポートし、相手を動かすことで最大の利益を生む関係です。"
    if (eb,ea) in _SOUSEI: return f"仕事のエネルギーが{nb}様から{na}様へ流れています。相手の提案をあなたが受け取り、最終決定を下す関係です。"
    if (ea,eb) in _SOUKOKU: return f"{na}様が{nb}様を【コントロール】しやすい関係です。上司やクライアントとして非常にスムーズに指示が通る相性です。"
    if (eb,ea) in _SOUKOKU: return f"{nb}様が{na}様を【コントロール】する力関係です。相手を適度に立てて主導権を譲るのが賢い処世術です。"
    return "互いに独立したプロとして良い緊張感を持って働ける関係です。"

def _combat_style(ra: str, rb: str) -> str:
    if ra == rb: return "社会や顧客に対する【戦闘スタイルが完全一致】しています。営業やプレゼンで抜群のコンビネーションを発揮します。"
    return "社会への【アプローチ手法が異なります】。新規開拓と顧客フォローなど、見事な役割分担（最強の矛と盾）が構築できます。"

def _crisis_management(fa: str, fb: str) -> str:
    if fa == fb: return "トラブル時の【危機管理思考が同じ】です。危機的状況下でも足並みが揃い、迅速な意思決定が可能です。"
    return "【危機管理アプローチが異なります】。一方が焦っている時にもう一方が冷静に分析できる、ピンチほど補い合える関係です。"

def _tenchu_affinity(tc_a: str, tc_b: str, na: str, nb: str) -> str:
    if tc_a == "不明" or tc_b == "不明": return "それぞれのペースで着実にビジネスを進めることができます。"
    if tc_a == tc_b: return f"お二人は【{tc_a}天中殺】という同じバイオリズムを持っています。好機が完全一致し爆発的なスピード感を生みます。ただし運気低迷期も同時に訪れるため、資金・計画に余裕を持たせるリスクヘッジが必要です。"
    return f"お二人は「{tc_a}」と「{tc_b}」という異なるバイオリズムを持っています。一方の運気が落ちた時にもう一方が好調のため、業績が落ち込まない【最高峰のリスクヘッジ（補完関係）】が成立しています。"


# ─────────────────────────────────────────────
#  フォント検出（pathlib 相対パス対応 / 絶対パス廃止）
#
#  優先順位:
#    1. fonts/ipag.ttf     — アプリ同梱フォント（最優先）
#    2. fonts/ipamp.ttf    — 同梱フォント（代替）
#    3. Linux システムフォント（Streamlit Cloud / packages.txt でインストール）
#    4. Windows システムフォント（ローカル開発環境）
# ─────────────────────────────────────────────
@st.cache_resource
def find_japanese_font() -> str | None:
    candidates = [
        _APP_DIR / "fonts" / "ipag.ttf",       # ★同梱フォント最優先（IPA ゴシック）
        _APP_DIR / "fonts" / "ipamp.ttf",      # 同梱フォント代替（IPA 明朝）
        _APP_DIR / "fonts" / "NotoSansJP-Regular.ttf",
        Path("/usr/share/fonts/truetype/ipafont-gothic/ipag.ttf"),   # Linux
        Path("/usr/share/fonts/opentype/ipafont-mincho/ipamp.ttf"),
        Path("/usr/share/fonts/truetype/ipafont-mincho/ipamp.ttf"),
        Path("C:/Windows/Fonts/msmincho.ttc"),  # Windows（ローカル開発）
        Path("C:/Windows/Fonts/YuMincho-Regular.ttf"),
        Path("C:/Windows/Fonts/msgothic.ttc"),
        Path("C:/Windows/Fonts/meiryo.ttc"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


# ─────────────────────────────────────────────
#  PDF生成：ヘッダー画像（PIL / in-memory）
# ─────────────────────────────────────────────
def _header_img_personal(name: str, gototoku: dict, tc: str, font_path: str) -> BytesIO:
    from PIL import Image, ImageDraw, ImageFont
    width, height = 800, 240
    img = Image.new("RGB", (width, height), "#F7FAFC")
    draw = ImageDraw.Draw(img)
    draw.line([(0,40),(width,40)], fill="#E2E8F0", width=2)
    draw.line([(0,200),(width,200)], fill="#E2E8F0", width=2)
    try:
        fs = ImageFont.truetype(font_path, 14)
        fm = ImageFont.truetype(font_path, 16)
        fl = ImageFont.truetype(font_path, 24)
        fn = ImageFont.truetype(font_path, 20)
    except Exception:
        fs = fm = fl = fn = ImageFont.load_default()
    lc, tc_col = "#2B6CB0", "#2D3748"
    ox = 250
    dp = gototoku["day_pillar"]
    draw.text((ox+90, 10), f"{name} 様", font=fn, fill=tc_col)
    draw.rectangle([ox+20,70,ox+80,190], outline=lc, width=2)
    draw.line([(ox+20,100),(ox+80,100)], fill=lc, width=2)
    draw.line([(ox+20,140),(ox+80,140)], fill=lc, width=2)
    draw.text((ox+35,75), "日柱", font=fs, fill=tc_col)
    draw.text((ox+35,108), dp[0], font=fl, fill=tc_col)
    draw.text((ox+35,150), dp[1], font=fl, fill=tc_col)
    draw.text((ox+25,205), f"天中殺: {tc}", font=fs, fill="#718096")
    stars = [gototoku["head"], gototoku["left"], gototoku["center"], gototoku["right"], gototoku["feet"]]
    sx, sy, gw, gh = ox+100, 45, 75, 50
    cross = [["",stars[0],""], [stars[1],stars[2],stars[3]], ["",stars[4],""]]
    for r in range(3):
        for c in range(3):
            if cross[r][c]:
                draw.rectangle([sx+c*gw, sy+r*gh, sx+gw+c*gw, sy+gh+r*gh], outline=lc, width=2)
                draw.text((sx+5+c*gw, sy+15+r*gh), cross[r][c], font=fm, fill=tc_col)
    buf = BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    return buf


def _header_img_business(na: str, ga: dict, tca: str,
                          nb: str, gb: dict, tcb: str, font_path: str) -> BytesIO:
    from PIL import Image, ImageDraw, ImageFont
    width, height = 800, 240
    img = Image.new("RGB", (width, height), "#F7FAFC")
    draw = ImageDraw.Draw(img)
    draw.line([(0,40),(width,40)], fill="#E2E8F0", width=2)
    draw.line([(0,200),(width,200)], fill="#E2E8F0", width=2)
    try:
        fs = ImageFont.truetype(font_path, 14)
        fm = ImageFont.truetype(font_path, 16)
        fl = ImageFont.truetype(font_path, 24)
        fn = ImageFont.truetype(font_path, 20)
    except Exception:
        fs = fm = fl = fn = ImageFont.load_default()
    lc, tc_col = "#2B6CB0", "#2D3748"
    def draw_person(ox, name, gototoku, tc):
        dp = gototoku["day_pillar"]
        stars = [gototoku["head"], gototoku["left"], gototoku["center"], gototoku["right"], gototoku["feet"]]
        draw.text((ox+90,10), f"{name} 様", font=fn, fill=tc_col)
        draw.rectangle([ox+20,70,ox+80,190], outline=lc, width=2)
        draw.line([(ox+20,100),(ox+80,100)], fill=lc, width=2)
        draw.line([(ox+20,140),(ox+80,140)], fill=lc, width=2)
        draw.text((ox+35,75), "日柱", font=fs, fill=tc_col)
        draw.text((ox+35,108), dp[0], font=fl, fill=tc_col)
        draw.text((ox+35,150), dp[1], font=fl, fill=tc_col)
        draw.text((ox+25,205), f"天中殺: {tc}", font=fs, fill="#718096")
        sx, sy, gw, gh = ox+100, 45, 75, 50
        cross = [["",stars[0],""], [stars[1],stars[2],stars[3]], ["",stars[4],""]]
        for r in range(3):
            for c in range(3):
                if cross[r][c]:
                    draw.rectangle([sx+c*gw,sy+r*gh,sx+gw+c*gw,sy+gh+r*gh], outline=lc, width=2)
                    draw.text((sx+5+c*gw,sy+15+r*gh), cross[r][c], font=fm, fill=tc_col)
    draw_person(10,  na, ga, tca)
    draw_person(430, nb, gb, tcb)
    buf = BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    return buf


# ─────────────────────────────────────────────
#  PDF生成：個人分析レポート（キャッシュ付き）
# ─────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def generate_personal_pdf(name: str, gototoku: dict, font_path: str) -> bytes:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    tc = get_tenchusatsu(gototoku["day_pillar"])
    img_buf = _header_img_personal(name, gototoku, tc, font_path)

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    # TTC フォントのカラーグリフ（絵文字テーブル）による
    # "Type 3 fonts with color glyphs are not supported" エラーを回避
    pdf.render_color_fonts = False
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(left=14, top=10, right=14)
    pdf.add_page()
    pdf.add_font("JP", fname=font_path)
    lh = 6.8

    pdf.set_fill_color(247, 250, 252)
    pdf.rect(0, 0, 210, 297, style="F")
    pdf.set_font("JP", size=22); pdf.set_text_color(26,32,44); pdf.set_xy(0, 10)
    pdf.cell(0, 10, text="【才能開花】自分専用・初期スペック解析カルテ",
             align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.image(img_buf, x=10, y=22, w=190)

    box_start_y = 84
    pdf.set_xy(15, 88)

    def heading(text):
        pdf.set_font("JP", size=13); pdf.set_text_color(43,108,176)
        pdf.write(lh, f"■ {text}\n"); pdf.set_x(15); pdf.ln(1.5)

    def strategy(label, star):
        data = STAR_DATA_PERSONAL.get(star, {"desc":"","strategy":""})
        pdf.set_font("JP", size=11); pdf.set_text_color(45,55,72)
        pdf.write(lh, f"【{label}】 ")
        pdf.set_font("JP", size=11.5); pdf.set_text_color(220,50,50)
        pdf.write(lh, f"{star}\n"); pdf.set_x(15)
        pdf.set_font("JP", size=11); pdf.set_text_color(45,55,72)
        pdf.write(lh, f"性質：{data['desc']}\n"); pdf.set_x(15)
        pdf.set_font("JP", style="U", size=11); pdf.set_text_color(26,32,44)
        pdf.write(lh, f"活かし方：{data['strategy']}\n"); pdf.set_x(15)
        pdf.set_font("JP", style="", size=11); pdf.ln(4.5); pdf.set_x(15)

    heading(f"{name}様の「5つの才能とサバイブ術」")
    strategy("本質・絶対に譲れない価値観（中央）", gototoku["center"])
    strategy("社会や上司に見せる外ヅラ（頭上）",    gototoku["head"])
    strategy("職場や同僚との接し方（右手）",        gototoku["right"])
    strategy("プライベート・家庭での顔（左手）",     gototoku["left"])
    strategy("ストレス時・無意識の行動（足元）",     gototoku["feet"])

    pdf.set_font("JP", size=11); pdf.set_text_color(45,55,72)
    pdf.write(lh, "■ あなたの人生バイオリズム（天中殺グループ）\n"); pdf.set_x(15)
    pdf.write(lh, f"あなたは【{tc}天中殺】グループに属しています。この時期は転職、起業、引っ越しなどの「人生の大きな決断」は避け、自己研鑽などの充電期間に充てるのが賢明なリスクヘッジとなります。\n")
    pdf.ln(3)

    box_end_y = pdf.get_y()
    bh = box_end_y - box_start_y
    pdf.set_draw_color(43,108,176); pdf.set_line_width(0.6)
    pdf.rect(10, box_start_y, 190, bh, style="D")
    pdf.set_line_width(0.2); pdf.rect(11, box_start_y+1, 188, bh-2, style="D")

    pdf.set_x(15); pdf.set_font("JP", size=11); pdf.set_text_color(45,55,72)
    pdf.multi_cell(178, lh, text=f"総括：以上が、{name}様が生まれ持った「初期スペック（才能の星）」です。今の仕事や人間関係で息苦しさを感じているなら、それは能力不足ではなく、星と環境のミスマッチが原因です。このカルテを、ご自身の才能を120%解放するための武器としてご活用ください！")

    # bytes() で明示キャスト（fpdf2 の版によって bytearray が返る場合の対策）
    return bytes(pdf.output())


# ─────────────────────────────────────────────
#  PDF生成：組織相性診断レポート（キャッシュ付き）
# ─────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def generate_business_pdf(name_a: str, ga: dict, name_b: str, gb: dict, font_path: str) -> bytes:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    tca = get_tenchusatsu(ga["day_pillar"])
    tcb = get_tenchusatsu(gb["day_pillar"])
    img_buf = _header_img_business(name_a, ga, tca, name_b, gb, tcb, font_path)

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.render_color_fonts = False
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(left=14, top=10, right=14)
    pdf.add_page()
    pdf.add_font("JP", fname=font_path)
    lh = 6.8

    pdf.set_fill_color(247,250,252); pdf.rect(0,0,210,297,style="F")
    pdf.set_fill_color(255,255,255); pdf.rect(10,84,190,194,style="F")
    pdf.set_font("JP", size=22); pdf.set_text_color(26,32,44); pdf.set_xy(0, 10)
    pdf.cell(0, 10, text="【ビジネス相性・完全攻略マニュアル】",
             align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.image(img_buf, x=10, y=22, w=190)

    pdf.set_draw_color(43,108,176); pdf.set_line_width(0.6)
    pdf.rect(10,84,190,194,style="D"); pdf.set_line_width(0.2); pdf.rect(11,85,188,192,style="D")
    pdf.set_xy(15, 88)

    def heading(text):
        pdf.set_font("JP", size=13); pdf.set_text_color(43,108,176)
        pdf.write(lh, f"■ {text}\n"); pdf.set_x(15)

    def normal(text):
        pdf.set_font("JP", size=11); pdf.set_text_color(45,55,72)
        pdf.write(lh, text+"\n"); pdf.set_x(15)

    def strategy(label, star):
        data = STAR_DATA_BUSINESS.get(star, {"desc":"","strategy":""})
        pdf.set_font("JP", size=11); pdf.set_text_color(45,55,72)
        pdf.write(lh, f"【{label}】 ")
        pdf.set_font("JP", size=11.5); pdf.set_text_color(220,50,50)
        pdf.write(lh, f"{star}\n"); pdf.set_x(15)
        pdf.set_font("JP", size=11); pdf.set_text_color(45,55,72)
        pdf.write(lh, f"性質：{data['desc']}\n"); pdf.set_x(15)
        pdf.set_font("JP", style="U", size=11); pdf.set_text_color(26,32,44)
        pdf.write(lh, f"攻略法：{data['strategy']}\n"); pdf.set_x(15)
        pdf.set_font("JP", style="", size=11); pdf.ln(1.2); pdf.set_x(15)

    def gap():
        pdf.ln(1.8); pdf.set_x(15)

    heading(f"{name_b}様の「取扱説明書」（地雷と攻略法）")
    strategy("本質・一番の価値観（中央）",         gb["center"])
    strategy("目上・社会に見せる顔（頭上）",        gb["head"])
    strategy("対人・現場での戦闘スタイル（右手）",  gb["right"])
    gap()
    heading("パワーバランスと立ち回り（主導権の所在）")
    normal(_power_balance(ga["center"], gb["center"], name_a, name_b))
    gap()
    heading("社会・顧客に対するアプローチ（戦闘スタイル）")
    normal(f"お二人の右手の星（{ga['right']}×{gb['right']}）の分析です。{_combat_style(ga['right'],gb['right'])}")
    gap()
    heading("トラブル時の危機管理能力（メンタルの補完）")
    normal(f"お二人の足元の星（{ga['feet']}×{gb['feet']}）の分析です。{_crisis_management(ga['feet'],gb['feet'])}")
    gap()
    heading("事業バイオリズムとリスクヘッジ（天中殺グループ）")
    normal(_tenchu_affinity(tca, tcb, name_a, name_b))

    # bytes() で明示キャスト（fpdf2 の版によって bytearray が返る場合の対策）
    return bytes(pdf.output())


# ─────────────────────────────────────────────
#  解析演出（プログレスバー + 広告プレースホルダー）
# ─────────────────────────────────────────────
_AD_HTML = """
<div style="border:2px dashed #d1d5db;border-radius:8px;background:#f9fafb;
            padding:16px 20px;text-align:center;margin:8px 0;">
  <div style="font-size:0.65rem;font-weight:700;text-transform:uppercase;
              letter-spacing:0.12em;color:#d1d5db;margin-bottom:4px;">AD</div>
  <div style="font-size:0.75rem;color:#9ca3af;">Google AdSense 広告プレースホルダー</div>
  <div style="font-size:0.68rem;color:#d1d5db;margin-top:2px;">728×90 / レスポンシブ広告ユニット</div>
</div>
"""

_STEPS = ["生年月日データを解析中...", "五行バランスを算出中...",
          "組織適正タイプを特定中...", "レポートを生成中..."]

def run_analysis_animation(slot) -> None:
    with slot.container():
        st.markdown(
            "<p style='font-size:0.9rem;font-weight:700;color:#1d4ed8;margin:4px 0 8px;'>"
            "⚙️ 組織適正化データをディープ解析中...</p>",
            unsafe_allow_html=True,
        )
        bar   = st.progress(0)
        label = st.empty()
        st.markdown(_AD_HTML, unsafe_allow_html=True)
        n = len(_STEPS)
        for i, msg in enumerate(_STEPS):
            label.caption(msg)
            sub = 20
            for j in range(sub):
                bar.progress((i * sub + j + 1) / (n * sub))
                time.sleep(3.0 / (n * sub))
        bar.progress(1.0)
        label.caption("解析完了。")
        time.sleep(0.3)
    slot.empty()


# ─────────────────────────────────────────────
#  カスタム CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
.main .block-container { max-width:680px; padding:0.75rem 1rem 3rem; }

/* ヘッダー */
.app-header { background:linear-gradient(135deg,#1e3a5f 0%,#1d4ed8 100%);
              border-radius:12px; padding:22px 24px 18px; margin-bottom:8px; }
.app-title  { font-size:1.45rem; font-weight:900; color:#fff; margin:0 0 3px;
              letter-spacing:-0.025em; }
.app-sub    { font-size:0.7rem; color:rgba(255,255,255,0.6); letter-spacing:0.13em; margin:0; }

/* ── 五徳チャート ── */
.gototoku-wrap {
  background:#f8faff; border:1px solid #dbeafe; border-radius:12px;
  padding:20px 16px 16px; margin:12px 0;
}
.gototoku-title {
  font-size:0.72rem; font-weight:700; color:#6b7280; text-transform:uppercase;
  letter-spacing:0.1em; margin:0 0 14px; text-align:center;
}
.gt-grid {
  display:grid;
  grid-template-columns: 1fr 1fr 1fr;
  grid-template-rows: auto auto auto;
  gap: 8px;
  max-width: 340px;
  margin: 0 auto;
}
.gt-cell {
  background:#fff; border:1px solid #e0e7ff; border-radius:8px;
  padding:10px 8px; text-align:center;
}
.gt-cell.center {
  background:#eff6ff; border-color:#bfdbfe; border-width:2px;
}
.gt-cell.head, .gt-cell.feet { grid-column: 2; }
.gt-cell.head   { grid-row: 1; }
.gt-cell.left   { grid-row: 2; grid-column: 1; }
.gt-cell.center { grid-row: 2; grid-column: 2; }
.gt-cell.right  { grid-row: 2; grid-column: 3; }
.gt-cell.feet   { grid-row: 3; }
.gt-pos  { font-size:0.62rem; font-weight:700; color:#9ca3af; margin:0 0 3px; letter-spacing:0.05em; }
.gt-star { font-size:0.92rem; font-weight:800; color:#1e3a5f; margin:0; }
.gt-star.center-star { color:#1d4ed8; font-size:1rem; }

/* 中心星カード */
.star-card {
  background:#eff6ff; border:1px solid #bfdbfe; border-left:5px solid #1d4ed8;
  border-radius:8px; padding:18px 20px; margin:10px 0;
}
.star-card-b {
  background:#f5f3ff; border:1px solid #ddd6fe; border-left:5px solid #7c3aed;
  border-radius:8px; padding:18px 20px; margin:10px 0;
}
.star-name-lg { font-size:1.4rem; font-weight:900; color:#1e3a5f; margin:0 0 6px; }
.star-name-sm { font-size:1.05rem; font-weight:800; color:#1e3a5f; margin:0 0 4px; }
.star-name-b  { color:#4c1d95 !important; }
.star-desc    { font-size:0.9rem; color:#374151; line-height:1.65; margin:0; }
.member-label { font-size:0.7rem; font-weight:700; color:#6b7280; text-transform:uppercase;
                letter-spacing:0.08em; margin-bottom:4px; }

/* 相性カード */
.compat-card {
  background:#f0fdf4; border:1px solid #bbf7d0; border-left:5px solid #16a34a;
  border-radius:8px; padding:18px 20px; margin:10px 0;
}
.compat-badge {
  display:inline-block; background:#16a34a; color:#fff; border-radius:20px;
  padding:3px 14px; font-size:0.78rem; font-weight:700; margin-bottom:10px;
}
.compat-text { font-size:0.92rem; color:#374151; line-height:1.65; margin:0; }

/* アップセルカード */
.upsell-card {
  background:#fffbeb; border:1px solid #fde68a; border-left:5px solid #d97706;
  border-radius:8px; padding:18px 20px; margin:10px 0;
}

/* 柱タグ */
.pillar-tag {
  display:inline-block; background:#1d4ed8; color:#fff; border-radius:4px;
  padding:1px 8px; font-size:0.78rem; font-weight:600; margin:0 3px;
}
.pillar-row { font-size:0.8rem; color:#6b7280; margin-bottom:6px; }

/* 決済ペイウォール */
.paywall-card {
  background:#f0f9ff; border:2px solid #0ea5e9; border-radius:12px;
  padding:22px 24px; margin:12px 0;
}
.paywall-price {
  font-size:1.8rem; font-weight:900; color:#0c4a6e; margin:8px 0;
  letter-spacing:-0.04em;
}
.paywall-confirm {
  background:#fff7ed; border:2px solid #fb923c; border-radius:12px;
  padding:20px 22px; margin:12px 0;
}
.paid-badge {
  background:#dcfce7; border:1px solid #86efac; border-radius:8px;
  padding:12px 16px; margin:8px 0; text-align:center;
  font-size:0.95rem; font-weight:700; color:#166534;
}

/* 非表示 */
#MainMenu, footer, header { visibility:hidden; }

/* スマホ */
@media (max-width:480px) {
  .app-title { font-size:1.1rem; }
  .star-name-lg { font-size:1.15rem; }
  .main .block-container { padding:0.5rem 0.5rem 3rem; }
  .gt-star { font-size:0.82rem; }
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
#  五徳チャート HTML を生成するヘルパー
# ─────────────────────────────────────────────
def gototoku_html(g: dict) -> str:
    def cell(pos_key: str) -> str:
        label = POSITION_LABELS[pos_key]
        star  = g[pos_key]
        is_center = pos_key == "center"
        star_cls  = "gt-star center-star" if is_center else "gt-star"
        return (
            f'<div class="gt-cell {pos_key}">'
            f'<p class="gt-pos">{label}</p>'
            f'<p class="{star_cls}">{star}</p>'
            f'</div>'
        )
    return f"""
<div class="gototoku-wrap">
  <p class="gototoku-title">🔷 ポジション別 適性マップ（五徳）</p>
  <div class="gt-grid">
    {cell("head")}
    {cell("left")}
    {cell("center")}
    {cell("right")}
    {cell("feet")}
  </div>
</div>
"""


# ─────────────────────────────────────────────
#  ヘッダー
# ─────────────────────────────────────────────
st.markdown("""
<div class="app-header" translate="no">
  <p class="app-title">📊 組織適正化シミュレーター</p>
  <p class="app-sub">ORGANIZATION OPTIMIZATION ANALYZER &nbsp;·&nbsp; BETA v2.0</p>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  セッション状態の初期化
# ─────────────────────────────────────────────
for _k, _v in {
    "p1_result": None, "p1_name": "", "p1_birth": None,
    "show_paywall_p1": False, "paid_p1": False, "stripe_url_p1": None,
    "c_result_a": None, "c_result_b": None,
    "c_name_a": "", "c_name_b": "",
    "show_paywall_c": False, "paid_c": False, "stripe_url_c": None,
    "just_paid": "",   # "p1" or "c" — 決済完了バナー表示用（表示後に "" にリセット）
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ─────────────────────────────────────────────
#  Stripe 決済コールバック処理
#  success_url = {BASE_URL}?status=success&session_id={ID}&product=p1
#  ・?status=success を検知 → 決済完了と判断
#  ・?session_id で Stripe API を叩いて payment_status を二重検証
#  ・metadata から名前・生年月日を復元し、セッション状態を再構築
#  ・（本番URLに変える場合は secrets.toml の BASE_URL だけ書き換えればOK）
# ─────────────────────────────────────────────
_qs = st.query_params
if _qs.get("status") == "success":
    _sid      = _qs.get("session_id", "")
    _meta     = _retrieve_stripe_metadata(_sid) if (_STRIPE_READY and _sid) else None
    _product  = (_meta or {}).get("product", _qs.get("product", ""))
    _name_raw = (_meta or {}).get("name",    "")
    _birth_raw= (_meta or {}).get("birth",   "")

    if _product == "p1":
        st.session_state["paid_p1"]         = True
        st.session_state["show_paywall_p1"] = False
        st.session_state["stripe_url_p1"]   = None
        st.session_state["p1_name"]         = _name_raw
        # birth 復元 → 再計算
        if _birth_raw:
            try:
                _b = date.fromisoformat(_birth_raw)
                st.session_state["p1_result"] = calc_gototoku(_b)
                st.session_state["p1_birth"]  = _b
            except Exception:
                pass
        st.session_state["just_paid"] = "p1"

    elif _product == "c":
        st.session_state["paid_c"]          = True
        st.session_state["show_paywall_c"]  = False
        st.session_state["stripe_url_c"]    = None
        # name: "名前A|名前B"
        _names = _name_raw.split("|", 1)
        st.session_state["c_name_a"] = _names[0] if len(_names) > 0 else ""
        st.session_state["c_name_b"] = _names[1] if len(_names) > 1 else ""
        # birth: "YYYY-MM-DD|YYYY-MM-DD"
        _births = _birth_raw.split("|", 1)
        if len(_births) == 2:
            try:
                _ba = date.fromisoformat(_births[0])
                _bb = date.fromisoformat(_births[1])
                st.session_state["c_result_a"] = calc_gototoku(_ba)
                st.session_state["c_result_b"] = calc_gototoku(_bb)
            except Exception:
                pass
        st.session_state["just_paid"] = "c"

    st.query_params.clear()  # URL からクエリパラメータを除去してリダイレクト先をクリーンに
    st.rerun()

# ─────────────────────────────────────────────
#  決済完了バナー（Stripe コールバック直後に 1 回だけ表示）
# ─────────────────────────────────────────────
if st.session_state.get("just_paid"):
    _jp = st.session_state["just_paid"]
    _jp_label = "個人分析レポート（¥980）" if _jp == "p1" else "組織相性診断レポート（¥1,480）"
    st.success(
        f"✅ 決済が完了しました！「{_jp_label}」のPDFをダウンロードしてください。"
        f"  下のタブにダウンロードボタンが表示されています。"
    )
    st.session_state["just_paid"] = ""  # 次の操作で再表示しない

# ─────────────────────────────────────────────
#  タブ
# ─────────────────────────────────────────────
tab1, tab2 = st.tabs(["👤 個人分析", "🤝 組織相性診断"])


# ══════════════════════════════════════════════
#  TAB 1：個人分析
# ══════════════════════════════════════════════
with tab1:
    st.markdown(
        "<h2 style='font-size:1rem;font-weight:700;margin:0 0 2px;'>メンバーの適性タイプを特定する</h2>",
        unsafe_allow_html=True,
    )
    st.caption("生年月日から、その人材が最もパフォーマンスを発揮できる役割・働き方を診断します。")

    p1_name = st.text_input("氏名（レポートに表示）", value=st.session_state["p1_name"],
                             placeholder="例：田中 太郎", key="p1_name_input")

    c_date, c_btn = st.columns([3, 1])
    with c_date:
        birth1 = st.date_input(
            "生年月日を選択してください（YYYY/MM/DD）",
            value=date(1985, 6, 15),
            min_value=date(1924, 2, 5),
            max_value=date(2006, 12, 31),
            format="YYYY/MM/DD",
            key="p1_birth_input",
        )
    with c_btn:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        run1 = st.button("診断実行", type="primary", key="p1_btn", use_container_width=True)

    if run1:
        anim_slot = st.empty()
        run_analysis_animation(anim_slot)
        g = calc_gototoku(birth1)
        st.session_state["p1_result"]        = g
        st.session_state["p1_name"]          = p1_name
        st.session_state["show_paywall_p1"]  = False
        st.session_state["paid_p1"]          = False

    # ─── 結果表示（セッションから取得）───
    if st.session_state["p1_result"]:
        g     = st.session_state["p1_result"]
        _name = st.session_state["p1_name"] or "ゲスト"

        # 柱コード
        st.markdown(f"""
<div class="pillar-row">
  日柱&nbsp;<span class="pillar-tag">{g['day_pillar']}</span>
  &nbsp;月柱&nbsp;<span class="pillar-tag">{g['month_pillar']}</span>
  &nbsp;年柱&nbsp;<span class="pillar-tag">{g['year_pillar']}</span>
</div>
        """, unsafe_allow_html=True)

        # 五徳チャート
        st.markdown(gototoku_html(g), unsafe_allow_html=True)

        # 中心星（中央）の詳細プロフィール
        center_star = g["center"]
        st.markdown(
            f'<h3 style="font-size:0.85rem;font-weight:700;color:#6b7280;'
            f'text-transform:uppercase;letter-spacing:0.08em;margin:14px 0 4px;">'
            f'中心星（中央）詳細 — {center_star}</h3>',
            unsafe_allow_html=True,
        )
        st.markdown(f"""
<div class="star-card">
  <p class="star-name-lg">{center_star}</p>
  <p class="star-desc">{STAR_PROFILE[center_star]}</p>
</div>
        """, unsafe_allow_html=True)

        with st.expander("📋 全10タイプ 対応表"):
            for sn, sd in STAR_PROFILE.items():
                if sn == center_star:
                    st.markdown(f"**▶ {sn}**　{sd}")
                else:
                    st.markdown(f"　{sn}　{sd}")

        st.divider()

        # ─── ペイウォール ───────────────────────────
        if st.session_state["paid_p1"]:
            st.markdown('<div class="paid-badge">✅ ご購入ありがとうございます！PDFを受け取ってください。</div>',
                        unsafe_allow_html=True)
            font_path = find_japanese_font()
            if font_path:
                pdf_bytes = generate_personal_pdf(_name, g, font_path)
                st.download_button(
                    label="⬇️ 個人分析レポート（PDF）をダウンロード",
                    data=bytes(pdf_bytes),   # bytearray → bytes 明示キャスト
                    file_name=f"Personal_Report_{_name}様.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            else:
                st.error("日本語フォントが見つかりません。fonts/ipag.ttf を配置するか、packages.txt を確認してください。")

        elif st.session_state["show_paywall_p1"]:
            st.markdown("""
<div class="paywall-confirm">
  <p style="font-size:0.95rem;font-weight:800;color:#9a3412;margin:0 0 8px;">💳 ご購入確認</p>
  <p style="font-size:0.88rem;color:#374151;margin:0 0 6px;">
    <b>商品：</b>個人分析レポート（完全版 PDF・A4×1枚）<br>
    <b>内容：</b>5つの才能と地雷業務・天中殺バイオリズム詳細解析<br>
    <b>金額：</b>¥980（税込）
  </p>
</div>
            """, unsafe_allow_html=True)
            _su_p1 = st.session_state.get("stripe_url_p1")
            if _STRIPE_READY and _su_p1:
                st.link_button("💳 Stripeで決済してPDFを取得する", url=_su_p1,
                               type="primary", use_container_width=True)
                if st.button("キャンセル", key="p1_pay_ng", use_container_width=True):
                    st.session_state["show_paywall_p1"] = False
                    st.session_state["stripe_url_p1"]   = None
                    st.rerun()
            else:
                col_ok, col_ng = st.columns(2)
                with col_ok:
                    if st.button("✅ 購入を確定する（デモ）", type="primary",
                                 key="p1_pay_ok", use_container_width=True):
                        st.session_state["paid_p1"]          = True
                        st.session_state["show_paywall_p1"]  = False
                        st.rerun()
                with col_ng:
                    if st.button("キャンセル", key="p1_pay_ng", use_container_width=True):
                        st.session_state["show_paywall_p1"] = False
                        st.rerun()

        else:
            # ── サンプルレポート画像 ──────────────────────
            _img_p1 = _APP_DIR / "sample_980.png"
            if _img_p1.exists():
                st.image(str(_img_p1), caption="【サンプル】個人分析レポート（¥980）")

            st.markdown("""
<div class="paywall-card">
  <h3 style="font-size:1rem;font-weight:800;color:#0c4a6e;margin:0 0 6px;">
    📋 完全版レポートで「才能の地図」を手に入れる
  </h3>
  <p style="font-size:0.87rem;color:#374151;line-height:1.65;margin:0 0 10px;">
    ✓ 5つの星それぞれの<b>「地雷業務」と「サバイブ術」</b>を詳細解析<br>
    ✓ <b>天中殺グループ</b>（人生バイオリズム）の分析<br>
    ✓ ビジネス取扱説明書 <b>PDF（A4・1枚）</b>を即座に生成
  </p>
  <p class="paywall-price">¥980 <span style="font-size:0.9rem;font-weight:400;color:#64748b;">（税込）</span></p>
</div>
            """, unsafe_allow_html=True)
            # ── ティザーモード：決済ボタンを一時的に無効化 ──
            # ▼ 本番公開時はこの行を削除し、下の実装ブロックのコメントを解除する
            st.button("🔒 現在、決済システム準備中（近日公開予定）",
                      key="p1_buy_btn", disabled=True, use_container_width=True)
            # ── 本番実装ブロック（決済システム公開後に解除） ──────────────
            # if st.button("🛒 完全版PDFをダウンロードする", type="primary",
            #              key="p1_buy_btn", use_container_width=True):
            #     if _STRIPE_READY:
            #         _url = _create_checkout_session(
            #             _PRICE_P1, "p1",
            #             name=p1_name,
            #             birth_str=str(birth1),
            #         )
            #         if _url:
            #             st.session_state["stripe_url_p1"] = _url
            #     st.session_state["show_paywall_p1"] = True
            #     st.rerun()
            # ─────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════
#  TAB 2：組織相性診断
# ══════════════════════════════════════════════
with tab2:
    st.markdown(
        "<h2 style='font-size:1rem;font-weight:700;margin:0 0 2px;'>2名の組織相性を診断する</h2>",
        unsafe_allow_html=True,
    )
    st.caption("マネージャーと部下、またはチームメンバー2名の相性を分析し、最適な役割分担を特定します。")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(
            "<p style='font-size:0.8rem;font-weight:700;margin:0 0 4px;color:#374151;'>"
            "▍ メンバー A（自分）</p>",
            unsafe_allow_html=True,
        )
        name_a = st.text_input("氏名 A", value=st.session_state["c_name_a"],
                               placeholder="氏名（例：田中 太郎）", key="c_name_a_input",
                               label_visibility="collapsed")
        st.markdown(
            "<p style='font-size:0.72rem;color:#6b7280;margin:6px 0 2px;'>生年月日（YYYY/MM/DD）</p>",
            unsafe_allow_html=True,
        )
        birth_a = st.date_input(
            "生年月日 A",
            value=date(1982, 3, 10),
            min_value=date(1924, 2, 5),
            max_value=date(2006, 12, 31),
            format="YYYY/MM/DD",
            key="c_birth_a",
            label_visibility="collapsed",
        )
    with col_b:
        st.markdown(
            "<p style='font-size:0.8rem;font-weight:700;margin:0 0 4px;color:#374151;'>"
            "▍ メンバー B（相手）</p>",
            unsafe_allow_html=True,
        )
        name_b = st.text_input("氏名 B", value=st.session_state["c_name_b"],
                               placeholder="氏名（例：鈴木 花子）", key="c_name_b_input",
                               label_visibility="collapsed")
        st.markdown(
            "<p style='font-size:0.72rem;color:#6b7280;margin:6px 0 2px;'>生年月日（YYYY/MM/DD）</p>",
            unsafe_allow_html=True,
        )
        birth_b = st.date_input(
            "生年月日 B",
            value=date(1993, 11, 25),
            min_value=date(1924, 2, 5),
            max_value=date(2006, 12, 31),
            format="YYYY/MM/DD",
            key="c_birth_b",
            label_visibility="collapsed",
        )

    run2 = st.button("相性を分析する", type="primary", key="c_btn", use_container_width=True)

    if run2:
        anim_slot2 = st.empty()
        run_analysis_animation(anim_slot2)
        ga = calc_gototoku(birth_a)
        gb = calc_gototoku(birth_b)
        st.session_state["c_result_a"]     = ga
        st.session_state["c_result_b"]     = gb
        st.session_state["c_name_a"]       = name_a
        st.session_state["c_name_b"]       = name_b
        st.session_state["show_paywall_c"] = False
        st.session_state["paid_c"]         = False

    # ─── 結果表示（セッションから取得）───
    if st.session_state["c_result_a"] and st.session_state["c_result_b"]:
        ga     = st.session_state["c_result_a"]
        gb     = st.session_state["c_result_b"]
        _na    = st.session_state["c_name_a"] or "メンバーA"
        _nb    = st.session_state["c_name_b"] or "メンバーB"
        star_a = ga["center"]
        star_b = gb["center"]
        compat = COMPATIBILITY_LOGIC["same" if star_a == star_b else "different"]

        # 各メンバーカード
        col_ra, col_rb = st.columns(2)
        with col_ra:
            st.markdown(f"""
<div class="star-card" style="margin-top:10px;">
  <div class="member-label">{_na} &nbsp;·&nbsp; {ga['day_pillar']}日</div>
  <p class="star-name-sm">{star_a}</p>
  <p class="star-desc" style="font-size:0.83rem;">{STAR_PROFILE[star_a]}</p>
</div>
            """, unsafe_allow_html=True)
        with col_rb:
            st.markdown(f"""
<div class="star-card-b" style="margin-top:10px;">
  <div class="member-label">{_nb} &nbsp;·&nbsp; {gb['day_pillar']}日</div>
  <p class="star-name-sm star-name-b">{star_b}</p>
  <p class="star-desc" style="font-size:0.83rem;">{STAR_PROFILE[star_b]}</p>
</div>
            """, unsafe_allow_html=True)

        # 相性結果
        st.markdown(f"""
<div class="compat-card">
  <div class="compat-badge">相性タイプ</div>
  <p style="font-weight:800;font-size:1rem;color:#064e3b;margin:0 0 8px;">{compat['title']}</p>
  <p class="compat-text">{compat['text']}</p>
</div>
        """, unsafe_allow_html=True)

        st.divider()

        # ─── ペイウォール ───────────────────────────
        if st.session_state["paid_c"]:
            st.markdown('<div class="paid-badge">✅ ご購入ありがとうございます！PDFを受け取ってください。</div>',
                        unsafe_allow_html=True)
            font_path = find_japanese_font()
            if font_path:
                pdf_bytes = generate_business_pdf(_na, ga, _nb, gb, font_path)
                st.download_button(
                    label="⬇️ 組織相性診断レポート（PDF）をダウンロード",
                    data=bytes(pdf_bytes),   # bytearray → bytes 明示キャスト
                    file_name=f"Business_Report_{_na}×{_nb}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            else:
                st.error("日本語フォントが見つかりません。fonts/ipag.ttf を配置するか、packages.txt を確認してください。")

        elif st.session_state["show_paywall_c"]:
            st.markdown(f"""
<div class="paywall-confirm">
  <p style="font-size:0.95rem;font-weight:800;color:#9a3412;margin:0 0 8px;">💳 ご購入確認</p>
  <p style="font-size:0.88rem;color:#374151;margin:0 0 6px;">
    <b>商品：</b>組織相性診断レポート（完全版 PDF・A4×1枚）<br>
    <b>内容：</b>{_nb}様の「取扱説明書」＋パワーバランス・天中殺 詳細解析<br>
    <b>金額：</b>¥1,480（税込）
  </p>
</div>
            """, unsafe_allow_html=True)
            _su_c = st.session_state.get("stripe_url_c")
            if _STRIPE_READY and _su_c:
                st.link_button("💳 Stripeで決済してPDFを取得する", url=_su_c,
                               type="primary", use_container_width=True)
                if st.button("キャンセル", key="c_pay_ng", use_container_width=True):
                    st.session_state["show_paywall_c"] = False
                    st.session_state["stripe_url_c"]   = None
                    st.rerun()
            else:
                col_ok, col_ng = st.columns(2)
                with col_ok:
                    if st.button("✅ 購入を確定する（デモ）", type="primary",
                                 key="c_pay_ok", use_container_width=True):
                        st.session_state["paid_c"]          = True
                        st.session_state["show_paywall_c"]  = False
                        st.rerun()
                with col_ng:
                    if st.button("キャンセル", key="c_pay_ng", use_container_width=True):
                        st.session_state["show_paywall_c"] = False
                        st.rerun()

        else:
            # ── サンプルレポート画像 ──────────────────────
            _img_c = _APP_DIR / "sample_1480.png"
            if _img_c.exists():
                st.image(str(_img_c), caption="【サンプル】組織相性診断レポート（¥1,480）")

            st.markdown(f"""
<div class="paywall-card">
  <h3 style="font-size:1rem;font-weight:800;color:#0c4a6e;margin:0 0 6px;">
    📋 完全版レポートで「最強の組み合わせ」を解析する
  </h3>
  <p style="font-size:0.87rem;color:#374151;line-height:1.65;margin:0 0 10px;">
    ✓ {_nb}様の<b>「取扱説明書」（地雷と攻略法）</b>を5ポジション全解析<br>
    ✓ <b>パワーバランス・戦闘スタイル・危機管理</b>の相性詳細<br>
    ✓ <b>天中殺バイオリズム</b>でリスクヘッジを自動診断<br>
    ✓ 組織相性完全版 <b>PDF（A4・1枚）</b>を即座に生成
  </p>
  <p class="paywall-price">¥1,480 <span style="font-size:0.9rem;font-weight:400;color:#64748b;">（税込）</span></p>
</div>
            """, unsafe_allow_html=True)
            # ── ティザーモード：決済ボタンを一時的に無効化 ──
            # ▼ 本番公開時はこの行を削除し、下の実装ブロックのコメントを解除する
            st.button("🔒 現在、決済システム準備中（近日公開予定）",
                      key="c_buy_btn", disabled=True, use_container_width=True)
            # ── 本番実装ブロック（決済システム公開後に解除） ──────────────
            # if st.button("🛒 完全版 組織相性PDFをダウンロードする", type="primary",
            #              key="c_buy_btn", use_container_width=True):
            #     if _STRIPE_READY:
            #         _url = _create_checkout_session(
            #             _PRICE_BUSI, "c",
            #             name=f"{name_a}|{name_b}",
            #             birth_str=f"{birth_a}|{birth_b}",
            #         )
            #         if _url:
            #             st.session_state["stripe_url_c"] = _url
            #     st.session_state["show_paywall_c"] = True
            #     st.rerun()
            # ─────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════
#  法人・大人数向け問い合わせセクション
#  （タブの外・ページ最下部に常時表示）
# ══════════════════════════════════════════════
st.markdown("<div style='margin-top:48px;'></div>", unsafe_allow_html=True)
st.info(
    "### 🏢 法人様・20名以上の組織診断をご希望の方へ\n\n"
    "チーム全員の適性診断・組織最適化コンサルティングを承ります。  \n"
    "人数・ご予算に応じたお見積りを無料でご提供します。お気軽にご相談ください。",
    icon="📩",
)
# ▼ Google フォームの URL をここに貼り付けてください
_FORM_URL = "https://forms.gle/XXXXXXXXXXXXXXXXXX"   # ← 実際の URL に差し替える

st.link_button(
    "📋 お問い合わせ・お見積りはこちら（Googleフォーム）",
    url=_FORM_URL,
    use_container_width=True,
)
st.caption("※ ご返信は通常 1〜2 営業日以内です。")
