/* shogu-view-v1 / shogu-term-v2 : 処遇改善の計画書（Excel）から読み取った要点を並べる。
 *
 * ★見出しは【様式で使っている言葉】をそのまま使う。
 *   分かりやすく言い換えると、職員が原本を開いたときに
 *   同じものだと分からなくなる。監査でも使う言葉なのでそろえる。
 *
 * ★管理者の画面（/shogu）と職員の画面（/shogu/my）の両方から使う。
 *   同じ見た目を2か所に書くと、必ず片方だけ古くなる。
 *
 * ★見た目（CSS）もこの1つに入れて、最初に使うときだけ差し込む。
 *   画面ごとにCSSを書くと、そろえるのが難しくなる。
 */
(function () {
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function yen(n) {
    if (n === null || n === undefined || n === '') return '—';
    var v = Number(n);
    if (!isFinite(v)) return '—';
    return v.toLocaleString('ja-JP') + '円';
  }

  function css() {
    if (document.getElementById('sv-css')) return;
    var st = document.createElement('style');
    st.id = 'sv-css';
    st.textContent = [
      '.sv{border:1.5px solid #cfe3d4;border-radius:12px;background:#f7fbf8;padding:13px 14px;margin-top:10px;}',
      '.sv-h{font-size:0.8rem;font-weight:800;color:#1b5e20;margin-bottom:9px;line-height:1.6;}',
      '.sv-h span{font-weight:400;color:#5f6368;}',
      '.sv-money{display:grid;grid-template-columns:1fr 1fr;gap:9px;}',
      '.sv-box{background:#fff;border:1px solid #e0e0e0;border-radius:10px;padding:10px 11px;}',
      '.sv-box-t{font-size:0.72rem;color:#5f6368;line-height:1.5;}',
      '.sv-box-v{font-size:1.12rem;font-weight:800;color:#202124;margin-top:3px;}',
      '.sv-note{font-size:0.74rem;color:#5f6368;line-height:1.7;margin:9px 0 0;}',
      '.sv-sec{font-size:0.78rem;font-weight:800;color:#3c4043;margin:13px 0 5px;}',
      '.sv-off{background:#fff;border:1px solid #e0e0e0;border-radius:10px;padding:9px 11px;margin-bottom:6px;}',
      '.sv-kubun{display:inline-block;background:#1b5e20;color:#fff;border-radius:999px;',
      'padding:2px 11px;font-size:0.76rem;font-weight:800;}',
      '.sv-off-s{font-size:0.84rem;font-weight:700;color:#202124;margin-top:5px;}',
      '.sv-term{font-size:0.74rem;color:#5f6368;margin-top:3px;}',
      '.sv-fold{border-top:1px dashed #cfe3d4;margin-top:10px;}',
      '.sv-fold summary{cursor:pointer;font-size:0.8rem;font-weight:700;color:#1b5e20;padding:9px 0;}',
      '.sv-g{font-size:0.74rem;font-weight:800;color:#5f6368;margin:9px 0 3px;}',
      '.sv-i{font-size:0.78rem;color:#3c4043;line-height:1.75;padding-left:1.2em;text-indent:-1.2em;margin-bottom:3px;}',
      '.sv-i:before{content:"\\2713 ";color:#137333;font-weight:800;}',
      '.sv-foot{font-size:0.72rem;color:#9aa0a6;margin-top:11px;}',
      '@media (max-width:480px){.sv-money{grid-template-columns:1fr;}}'
    ].join('');
    document.head.appendChild(st);
  }

  /* 要点のHTMLを返す。読み取れていなければ空。 */
  window.shoguViewHtml = function (s) {
    if (!s || typeof s !== 'object') return '';
    css();
    var h = '<div class="sv">';

    var head = [];
    if (s.year) head.push(esc(s.year));
    if (s.kind) head.push(esc(s.kind));
    h += '<div class="sv-h">' + (head.join(' ') || '処遇改善の書類');
    var sub = [];
    if (s.corp) sub.push(esc(s.corp));
    if (s.to) sub.push('提出先 ' + esc(s.to));
    if (sub.length) h += '<br><span>' + sub.join('　／　') + '</span>';
    h += '</div>';

    /* お金。★この2つの関係がこの書類のいちばんの要点。 */
    if (s.kasan_yen || s.kaizen_yen) {
      var pre = s.year ? esc(s.year) + 'の' : '';
      h += '<div class="sv-money">'
        + '<div class="sv-box"><div class="sv-box-t">' + pre + '加算の見込額</div>'
        + '<div class="sv-box-v">' + yen(s.kasan_yen) + '</div></div>'
        + '<div class="sv-box"><div class="sv-box-t">' + pre + '賃金改善の見込額</div>'
        + '<div class="sv-box-v">' + yen(s.kaizen_yen) + '</div></div>'
        + '</div>'
        + '<p class="sv-note">処遇改善加算として給付される額は、'
        + '<b>職員の賃金改善のために全額支出します</b>。'
        + '賃金改善の見込額は、加算の見込額以上となることが要件です。</p>';
    }

    if (s.getsugaku_plan) {
      h += '<p class="sv-note">このうち<b>月額賃金改善による額</b>'
        + '（基本給又は決まって毎月支払われる手当による改善）は '
        + '<b>' + yen(s.getsugaku_plan) + '</b>。'
        + (s.getsugaku_need
            ? '処遇改善加算Ⅳ相当の見込額の１／２（' + yen(s.getsugaku_need) + '）以上'
              + 'であることが要件です。'
            : '')
        + '</p>';
    }

    /* 事業所ごとの加算区分 */
    if (s.offices && s.offices.length) {
      h += '<div class="sv-sec">算定する処遇改善加算の区分</div>';
      s.offices.forEach(function (o) {
        h += '<div class="sv-off">'
          + '<span class="sv-kubun">' + esc(o.kubun) + '</span>'
          + '<div class="sv-off-s">' + esc(o.service || o.name || '') + '</div>'
          + (o.term || o.yen
              ? '<div class="sv-term">' + esc(o.term || '')
                + (o.yen ? '　処遇改善加算の見込額 ' + yen(o.yen) : '') + '</div>'
              : '')
          + '</div>';
      });
    }

    /* 職場環境等要件。★これは職員への約束そのもの。 */
    if (s.env && s.env.length) {
      var byg = [], cur = null;
      s.env.forEach(function (e) {
        if (!cur || cur.g !== e.group) { cur = { g: e.group, items: [] }; byg.push(cur); }
        cur.items.push(e.text);
      });
      h += '<details class="sv-fold"><summary>職場環境等要件（'
        + s.env.length + '項目）</summary>';
      byg.forEach(function (g) {
        if (g.g) h += '<div class="sv-g">' + esc(g.g) + '</div>';
        g.items.forEach(function (t) { h += '<div class="sv-i">' + esc(t) + '</div>'; });
      });
      h += '</details>';
    }

    if (s.mieruka && s.mieruka.length) {
      h += '<details class="sv-fold"><summary>見える化要件（'
        + s.mieruka.length + '）</summary>';
      s.mieruka.forEach(function (t) { h += '<div class="sv-i">' + esc(t) + '</div>'; });
      h += '</details>';
    }

    var foot = [];
    if (s.pledge) foot.push(esc(s.pledge) + ' に誓約');
    foot.push('提出したExcelから読み取って並べたものです。正本は原本のファイルです。');
    h += '<div class="sv-foot">' + foot.join('　／　') + '</div>';

    h += '</div>';
    return h;
  };
})();
