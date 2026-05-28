(function(){
    document.querySelectorAll('a[href^="#"]').forEach(function(a){
        a.addEventListener('click',function(e){
            var href=this.getAttribute('href');
            if(!href||href==='#') return;
            e.preventDefault();
            var t=document.querySelector(href);
            if(t) t.scrollIntoView({behavior:'smooth',block:'start'});
        });
    });
})();

    });
})();

    });
})();

// ===== スライドショーデータ =====
var SLIDES = [
  {
    step:1,phase:'利用開始前',phaseColor:'#1a73e8',icon:'person_add',
    title:'利用者情報を登録する',subtitle:'まずはここから！基本情報が全ページに活きる',
    mockType:'patient_reg',
    points:[
      {icon:'badge',text:'氏名・生年月日・介護度を入力'},
      {icon:'flag',text:'短期・長期目標を設定（要介護は機能/活動/参加の3分類）'},
      {icon:'business',text:'ケアマネ事業所・担当者名を入力'},
    ],
    tip:'一度入力すれば、書類出力・評価・モニタリング全てに自動反映！',
    arrow:'↓ 毎日の記録へ'
  },
  {
    step:2,phase:'毎日',phaseColor:'#34a853',icon:'edit_note',
    title:'ケース記録を入力する',subtitle:'日々の気づきをカテゴリ別に記録',
    mockType:'daily_record',
    points:[
      {icon:'category',text:'心身状況・食事・入浴・訓練状況など9カテゴリ'},
      {icon:'mic',text:'音声入力・AIアシストで素早く入力できる'},
      {icon:'auto_awesome',text:'記録が積み重なってモニタリングの素材になる'},
    ],
    tip:'毎日少しずつ入力するのがコツ。月末にまとめて書く必要がなくなる！',
    arrow:'↓ 体力測定へ'
  },
  {
    step:3,phase:'月中',phaseColor:'#f9ab00',icon:'fitness_center',
    title:'体力測定・体重を記録する',subtitle:'測定データがグラフになって書類に反映',
    mockType:'fitness',
    points:[
      {icon:'monitor_weight',text:'体重・握力・TUG・CS-30を記録'},
      {icon:'show_chart',text:'直近6ヶ月のグラフが自動生成'},
      {icon:'picture_as_pdf',text:'書類出力時にグラフも一緒に印刷される'},
    ],
    tip:'3ヶ月以内のデータがあればデータ充足チェックも✅になる！',
    arrow:'↓ モニタリング生成へ'
  },
  {
    step:4,phase:'月末',phaseColor:'#e8710a',icon:'summarize',
    title:'モニタリングを生成する',subtitle:'AIがケース記録を読んで自動で要約',
    mockType:'monitoring_gen',
    points:[
      {icon:'calendar_month',text:'モニタリングページから対象月・利用者を選択'},
      {icon:'auto_awesome',text:'「AI生成」ボタンを押すだけで草稿完成'},
      {icon:'edit',text:'生成後に内容を確認・編集して保存'},
    ],
    tip:'毎日のケース記録が多いほどAIの精度が上がる！',
    arrow:'↓ 月次評価へ'
  },
  {
    step:5,phase:'月末',phaseColor:'#a142f4',icon:'assignment_turned_in',
    title:'月次評価を入力する',subtitle:'訓練記録・目標達成状況・満足度を記録',
    mockType:'evaluation',
    points:[
      {icon:'flag',text:'短期・長期目標の達成状況を選択（達成/一部達成/未達成）'},
      {icon:'trending_up',text:'訓練による変化・課題とその要因を入力'},
      {icon:'sentiment_satisfied',text:'利用者・家族の満足度・新しい希望を記録'},
    ],
    tip:'評価データが書類出力の目標達成状況欄に自動で入る！',
    arrow:'↓ データ充足チェックへ'
  },
  {
    step:6,phase:'書類出力前',phaseColor:'#1a73e8',icon:'checklist',
    title:'データ充足チェックを確認',subtitle:'全員分の準備状況を一覧で確認',
    mockType:'data_check',
    points:[
      {icon:'check_circle',text:'モニタリング✅・訓練記録✅・体力測定✅・体重✅'},
      {icon:'warning',text:'△（未入力）の項目をタップして入力画面へ'},
      {icon:'group',text:'全利用者分を一覧で確認できる'},
    ],
    tip:'全員が✅になったら書類出力の準備完了！',
    arrow:'↓ 印刷設定へ'
  },
  {
    step:7,phase:'書類出力',phaseColor:'#0f9d58',icon:'tune',
    title:'印刷設定を選ぶ',subtitle:'テンプレート・スタイル・印刷項目を設定',
    mockType:'print_settings',
    points:[
      {icon:'palette',text:'スタンダード・ナチュラル・フォーマルなど12種類のテンプレート'},
      {icon:'color_lens',text:'カラー／モノクロを選択'},
      {icon:'checklist',text:'印刷する項目（体重・握力・特記事項など）を選択'},
    ],
    tip:'施設のスタイルに合わせてテンプレートをカスタマイズできる！',
    arrow:'↓ プレビュー確認へ'
  },
  {
    step:8,phase:'書類出力',phaseColor:'#0f9d58',icon:'preview',
    title:'プレビューで確認する',subtitle:'印刷前に内容を確認・その場で編集も可能',
    mockType:'preview',
    points:[
      {icon:'visibility',text:'確認ボタンで個別プレビューを表示'},
      {icon:'edit',text:'モニタリング文章はプレビュー画面で直接編集・保存可能'},
      {icon:'zoom_in',text:'ピンチ操作で拡大して細部を確認'},
    ],
    tip:'プレビューで最終確認してから印刷すると安心！',
    arrow:'↓ PDF出力・印刷へ'
  },
  {
    step:9,phase:'書類出力',phaseColor:'#0f9d58',icon:'picture_as_pdf',
    title:'PDF出力または印刷する',subtitle:'1人ずつ or 全員一括で出力できる',
    mockType:'print_out',
    points:[
      {icon:'person',text:'個別印刷：各行の「印刷」ボタンで1人分を出力'},
      {icon:'groups',text:'一括印刷：「全員一括印刷」で全員分を一度に出力'},
      {icon:'download',text:'PDFダウンロードまたはブラウザの印刷ダイアログ経由で印刷'},
    ],
    tip:'一括印刷は全員分のPDFが自動生成されるので月末作業が大幅短縮！',
    arrow:'↓ 完了！'
  },
  {
    step:10,phase:'完了',phaseColor:'#1a73e8',icon:'celebration',
    title:'月次業務完了！',subtitle:'TASUKARUでこのサイクルを毎月繰り返す',
    mockType:'complete',
    points:[
      {icon:'loop',text:'毎日の記録 → 月末評価 → 書類出力のサイクル'},
      {icon:'trending_down',text:'記録が習慣化するほど月末作業が楽になる'},
      {icon:'favorite',text:'利用者ごとのデータが蓄積されケアの質が上がる'},
    ],
    tip:'まずは毎日のケース記録から始めてみよう！',
    arrow:null
  }
];

function renderMock(type, slide) {
  var imgMap = {
    'patient_reg': '/static/img/slideshow/slide_01.png',
    'daily_record': '/static/img/slideshow/slide_02.png',
    'daily_record2': '/static/img/slideshow/slide_03.png',
    'fitness': '/static/img/slideshow/slide_04.png',
    'monitoring_gen': '/static/img/slideshow/slide_05.png',
    'evaluation': '/static/img/slideshow/slide_06.png',
    'data_check': '/static/img/slideshow/slide_07.png',
    'print_settings': '/static/img/slideshow/slide_07.png',
    'preview': '/static/img/slideshow/slide_08.png',
    'print_out': '/static/img/slideshow/slide_07.png',
    'complete': null
  };
  var src = imgMap[type];
  if (!src) {
    // 完了スライドは絵文字
    return '<div style="text-align:center;padding:8px 0"><div style="font-size:56px;margin-bottom:8px">🎉</div><div style="font-size:1.05rem;font-weight:900;color:#1a73e8;margin-bottom:10px">月次業務完了！</div><div style="display:flex;justify-content:center;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:12px"><span style="background:#e8f0fe;color:#1a73e8;border-radius:20px;padding:4px 12px;font-size:0.72rem;font-weight:800">毎日記録</span><span style="color:#b0b8c1">→</span><span style="background:#f3e8fd;color:#a142f4;border-radius:20px;padding:4px 12px;font-size:0.72rem;font-weight:800">月末評価</span><span style="color:#b0b8c1">→</span><span style="background:#e8f5e9;color:#34a853;border-radius:20px;padding:4px 12px;font-size:0.72rem;font-weight:800">書類出力</span></div><div style="background:#f6f8ff;border-radius:14px;padding:12px;font-size:0.78rem;color:#202124;line-height:1.9;text-align:left">このサイクルを繰り返すことで<br><b style="color:#1a73e8">記録が積み重なり</b>、<br><b style="color:#34a853">ケアの質が上がり</b>、<br><b style="color:#a142f4">書類作業が楽になる！</b></div></div>';
  }
  return '<img src="' + src + '" style="width:100%;border-radius:16px;box-shadow:0 4px 16px rgba(0,0,0,0.12);display:block;" alt="">';
}

var _ssIdx = 0;
function openSlideshow() {
  var modal = document.getElementById('ss-modal');
  modal.style.display = 'flex'; modal.classList.add('is-active');
  document.body.style.overflow = 'hidden';
  _ssIdx = 0;
  renderSlide(0);
  renderDots();
}
function closeSlideshow() {
  document.getElementById('ss-modal').style.display = 'none';
  document.body.style.overflow = '';
}
function renderDots() {
  var d = document.getElementById('ss-dots');
  if (!d) return;
  d.innerHTML = SLIDES.map(function(s, i) {
    return '<div class="ss-dot' + (i === _ssIdx ? ' active' : '') + '" onclick="renderSlide('+i+');renderDots()"></div>';
  }).join('');
}
function renderSlide(idx) {
  _ssIdx = idx;
  var s = SLIDES[idx];
  var el = document.getElementById('ss-content');
  var pct = Math.round((s.step / SLIDES.length) * 100);
  el.innerHTML =
    '<div class="ss-progress-bar"><div class="ss-progress-fill" style="width:'+pct+'%"></div></div>' +
    '<div class="ss-phase" style="background:'+s.phaseColor+'22;color:'+s.phaseColor+'">' +
      '<span class="material-symbols-outlined" style="font-size:14px">'+s.icon+'</span>' +
      s.phase +
      '<span style="margin-left:auto;font-size:0.7rem;opacity:0.7">'+s.step+' / '+SLIDES.length+'</span>' +
    '</div>' +
    '<div class="ss-title">'+s.title+'</div>' +
    '<div class="ss-subtitle">'+s.subtitle+'</div>' +
    '<div class="ss-mock-wrap">'+renderMock(s.mockType, s)+'</div>' +
    '<div class="ss-points">' +
      s.points.map(function(p){
        return '<div class="ss-point"><span class="material-symbols-outlined ss-point-ic" style="color:'+s.phaseColor+'">'+p.icon+'</span><span class="ss-point-txt">'+p.text+'</span></div>';
      }).join('') +
    '</div>' +
    '<div class="ss-tip" style="border-left:4px solid '+s.phaseColor+';background:'+s.phaseColor+'18">' +
      '<span class="material-symbols-outlined" style="font-size:16px;color:'+s.phaseColor+';flex-shrink:0">lightbulb</span>' +
      '<span>'+s.tip+'</span>' +
    '</div>' +
    (s.arrow ? '<div class="ss-arrow">'+s.arrow+'</div>' : '');

  el.scrollTop = 0;
  document.getElementById('ss-prev').style.opacity = idx === 0 ? '0.3' : '1';
  var nextBtn = document.getElementById('ss-next');
  nextBtn.innerHTML = idx === SLIDES.length-1
    ? '<span class="material-symbols-outlined">close</span>'
    : '<span class="material-symbols-outlined">arrow_forward</span>';
  renderDots();
}
function ssNext() {
  if (_ssIdx >= SLIDES.length-1) { closeSlideshow(); return; }
  renderSlide(_ssIdx+1);
}
function ssPrev() {
  if (_ssIdx <= 0) return;
  renderSlide(_ssIdx-1);
}

// キーボード左右矢印キー対応
document.addEventListener('keydown', function(e){
  if (!document.getElementById('ss-modal') || document.getElementById('ss-modal').style.display==='none') return;
  if (e.key === 'ArrowRight') ssNext();
  if (e.key === 'ArrowLeft') ssPrev();
  if (e.key === 'Escape') closeSlideshow();
});

// タッチスワイプ
(function(){
  var startX = 0, startY = 0;
  document.addEventListener('touchstart', function(e){
    if (!document.getElementById('ss-modal') || document.getElementById('ss-modal').style.display==='none') return;
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
  }, {passive:true});
  document.addEventListener('touchend', function(e){
    if (!document.getElementById('ss-modal') || document.getElementById('ss-modal').style.display==='none') return;
    var dx = e.changedTouches[0].clientX - startX;
    var dy = e.changedTouches[0].clientY - startY;
    if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 50) {
      dx < 0 ? ssNext() : ssPrev();
    }
  }, {passive:true});
})();

// 既存ガイドのピンチ拡大
(function(){
  var scale = 1, lastScale = 1, startDist = 0;
  function getDist(t){ var dx=t[0].clientX-t[1].clientX,dy=t[0].clientY-t[1].clientY; return Math.sqrt(dx*dx+dy*dy); }
  document.addEventListener('touchstart', function(e){
    if (document.getElementById('ss-modal') && document.getElementById('ss-modal').style.display!=='none') return;
    if (e.touches.length===2){ startDist=getDist(e.touches); lastScale=scale; }
  }, {passive:true});
  document.addEventListener('touchmove', function(e){
    if (document.getElementById('ss-modal') && document.getElementById('ss-modal').style.display!=='none') return;
    if (e.touches.length===2){
      scale = Math.min(3, Math.max(1, lastScale*(getDist(e.touches)/startDist)));
      var el = document.querySelector('.gd');
      if(el){ el.style.transformOrigin='top center'; el.style.transform='scale('+scale+')'; el.style.transition='none'; }
    }
  }, {passive:true});
  document.addEventListener('touchend', function(e){
    if (e.touches.length<2 && scale<1.05){
      scale=1;
      var el=document.querySelector('.gd');
      if(el){ el.style.transform='scale(1)'; el.style.transition='transform 0.25s'; }
    }
  }, {passive:true});
})();
