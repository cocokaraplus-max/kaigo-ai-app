// TASUKARU スタートガイド スライドショー (guide-v2 : 実画面モック＋場所＋くわしい使い方)
window.__SS_FROM_JS__ = true;

// ページ内アンカーのスムーズスクロール
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

var IMGDIR = '/static/img/slideshow/';
var SLIDES = [
  {step:1,phase:'利用開始前',phaseColor:'#1a73e8',icon:'person_add',
   title:'利用者情報を登録する',subtitle:'まずはここから。基本情報が全ページに活きる',
   loc:'管理者MENU ＞ 利用者一覧・編集 ＞ 利用者名「編集」',img:IMGDIR+'guide01.png',
   points:['管理者MENUを開き「利用者一覧・編集」を選びます','登録する利用者の行の「編集」をタップ（新規は「＋新規追加」）','利用者番号・氏名・生年月日・介護度を入力（＊は必須）','ケアマネ事業所・担当者、短期／長期目標も入力します','「保存」をタップ。以降は書類・評価・モニタリングへ自動反映'],
   tip:'まもる君クラウドのCSVで、利用者情報を一括取込もできます。'},
  {step:2,phase:'毎日',phaseColor:'#dc2626',icon:'ecg_heart',
   title:'日々のバイタルを記録する',subtitle:'出欠はバイタルの有無で管理されます',
   loc:'下部メニュー ＞ バイタル',img:IMGDIR+'guide02.png',
   points:['下部メニューの「バイタル」を開きます','利用者を選びます','体温・脈拍・血圧・SpO2などを入力します','「バイタルを保存」をタップ','バイタルの入力＝その日の「出席」記録。入力が無い日は欠席として管理されます'],
   tip:'バイタルの測定をする事で、その方の出欠を管理できる仕組みになっています。'},
  {step:3,phase:'毎日',phaseColor:'#1a73e8',icon:'edit_note',
   title:'ケース記録を入力する',subtitle:'カテゴリごとの記録がモニタリングの素材に',
   loc:'下部メニュー ＞ 記録入力',img:IMGDIR+'guide03.png',
   points:['下部メニューの「記録入力」を開きます','利用者を選びます','カテゴリ（心身状況・食事・入浴・排泄・機能訓練 など）を選択','マイクで音声入力、または手入力で記録します','「記録を保存」。カテゴリ別の記録がモニタリング生成の素材になります'],
   tip:'毎日少しずつ入力するのがコツ。月末にまとめて書く必要がなくなります。'},
  {step:4,phase:'定期',phaseColor:'#c2185b',icon:'fitness_center',
   title:'体力測定・体重を記録する',subtitle:'測定データがグラフになって書類に反映',
   loc:'下部メニュー ＞ 体力・体重',img:IMGDIR+'guide04.png',
   points:['下部メニューの「体力・体重」を開きます','利用者を選びます','体重（kg）・備考を入力し「体重を保存」','握力・TUG・CS-30などの体力測定値も記録します','直近6ヶ月のグラフが自動生成され、書類出力にも反映されます'],
   tip:'3ヶ月以内のデータがあれば、データ充足チェックが✅になります。'},
  {step:5,phase:'月末',phaseColor:'#e8710a',icon:'auto_awesome',
   title:'モニタリングを生成する',subtitle:'AIがケース記録を読んで自動で要約',
   loc:'下部メニュー ＞ モニタリング',img:IMGDIR+'guide05.png',
   points:['下部メニューの「モニタリング」を開きます','①利用者を選ぶ → ②対象月 → ③生成モード（カテゴリ別／まとめて1本）を選択','「AIでモニタリング文章を生成」をタップ','生成された文章を確認。「コピー」で他の書式（Excel等）へ貼り付けも可能','「下書き保存」または「確定保存」で保存します'],
   tip:'毎日のケース記録が多いほど、AIの精度が上がります。'},
  {step:6,phase:'月末',phaseColor:'#a142f4',icon:'assignment_turned_in',
   title:'月次評価を入力する',subtitle:'目標の評価・機能訓練の評価を記録',
   loc:'引き出しメニュー ＞ 月次評価',img:IMGDIR+'guide06.png',
   points:['引き出しメニューから「月次評価」を開きます','「新規評価」を選び、利用者・対象月・評価者を設定（利用者を選ぶと入力欄が出ます）','短期／長期目標の達成状況（達成／一部達成／未達成）を選択','機能訓練の評価や、目標の変更・見直しを入力します','保存すると、モニタリング報告書に提出する素材になります'],
   tip:'目標の評価も機能訓練の評価も、この画面でまとめて行えます。'},
  {step:7,phase:'書類出力',phaseColor:'#0f9d58',icon:'print',
   title:'書類を出力する',subtitle:'ここでモニタリング報告書を出力',
   loc:'引き出しメニュー ＞ 書類出力',img:IMGDIR+'guide07.png',doc:IMGDIR+'guide07b_doc.png',
   points:['引き出しメニューから「書類出力」を開きます','対象年月・スタイル（カラー／モノクロ）・印刷順序を選びます','テンプレート（12種）を選択します','出力ページ数「1枚にまとめる／2枚でリッチに」を選択','確認して印刷・PDF出力（個別／全員一括）します'],
   tip:'カテゴリは先にモニタリングメニューで整えておきましょう。2枚出力なら体力測定結果などをゆったり配置できます。'},
  {step:8,phase:'便利機能',phaseColor:'#1558d0',icon:'groups',
   title:'担当者会議もAIにおまかせ',subtitle:'録音するだけで3つの書類を自動作成',
   loc:'引き出しメニュー ＞ 担当者会議',img:IMGDIR+'guide08.png',
   points:['担当者会議のページで「録音」を開始します','会議を音声録音するだけ。あとはAIにおまかせ','AIが自動で「担当者会議 議事録」を作成','「アセスメントシート」も会議内容から自動作成','「ICF分類（生活機能モデル図）」まで自動で整理します'],
   tip:'会議の記録・書類づくりの手間が大幅に減ります。'},
  {step:9,phase:'便利機能',phaseColor:'#2d7a4f',icon:'contact_page',
   title:'利用者情報をまとめて見る',subtitle:'家系図・既往歴・趣味嗜好までひと目で',
   loc:'利用者一覧 ＞ 利用者名 ＞ 利用者情報',img:IMGDIR+'guide09.png',
   points:['利用者情報ページを開きます','「見る／家系図／ICF」のタブで表示を切り替えます','家系図（ジェノグラム）で家族構成を把握（□男性 ○女性 ◎本人 ■故人 ┈同居）','家族を追加すると自動で家系図になります','既往歴・趣味嗜好など、利用者の情報をまとめて閲覧できます'],
   tip:'担当者会議で作ったICF分類も、この画面で確認できます。'},
  {step:10,phase:'まとめ',phaseColor:'#1a73e8',icon:'verified',
   title:'もっと安心・便利に',subtitle:'現役の介護職員が作った、使い続けられるアプリ',
   loc:'',img:IMGDIR+'guide10.png',
   points:['災害モード・オフライン対応：ネットが無くても使え、復旧後に自動同期','音声入力・AI読み上げなど、ほかにも便利機能が多数','毎日の記録 → 評価 → 書類出力 のサイクルを繰り返すほどラクになります'],
   tip:'まずは毎日のケース記録から始めてみましょう！'}
];

function renderMock(s){
  var h='<div style="position:relative;margin-bottom:4px;">' +
    '<img src="'+s.img+'" style="width:100%;border-radius:16px;box-shadow:0 4px 16px rgba(0,0,0,0.12);display:block;pointer-events:none;" alt="">' +
    '<div style="position:absolute;inset:0;border-radius:16px;border:3px solid #e0e0e0;pointer-events:none;"></div>' +
    '</div>';
  if(s.doc){
    h+='<div class="ss-dochd"><span class="material-symbols-outlined" style="font-size:17px;color:'+s.phaseColor+'">description</span>出力される書類（モニタリング報告書）のイメージ</div>';
    h+='<div style="position:relative;margin-bottom:4px;"><img src="'+s.doc+'" style="width:100%;border-radius:14px;box-shadow:0 4px 16px rgba(0,0,0,0.10);display:block;pointer-events:none;border:2px solid #cfe0fc;" alt=""></div>';
  }
  return h;
}

var _ssIdx = 0;
function openSlideshow(){
  var modal=document.getElementById('ss-modal');
  if(!modal) return;
  modal.style.display='flex'; modal.classList.add('is-active');
  document.body.style.overflow='hidden';
  _ssIdx=0; renderSlide(0); renderDots();
}
function closeSlideshow(){
  var modal=document.getElementById('ss-modal');
  if(modal) modal.style.display='none';
  document.body.style.overflow='';
}
function renderDots(){
  var d=document.getElementById('ss-dots'); if(!d) return;
  d.innerHTML=SLIDES.map(function(s,i){
    return '<div class="ss-dot'+(i===_ssIdx?' active':'')+'" onclick="renderSlide('+i+');renderDots()"></div>';
  }).join('');
}
function renderSlide(idx){
  _ssIdx=idx;
  var s=SLIDES[idx];
  var el=document.getElementById('ss-content'); if(!el) return;
  var pct=Math.round((s.step/SLIDES.length)*100);
  var loc=s.loc?('<div class="ss-loc"><span class="material-symbols-outlined" style="font-size:17px">location_on</span><b>ここにあります</b>　'+s.loc+'</div>'):'';
  el.innerHTML=
    '<div class="ss-progress-bar"><div class="ss-progress-fill" style="width:'+pct+'%"></div></div>' +
    '<div class="ss-phase" style="background:'+s.phaseColor+'22;color:'+s.phaseColor+'"><span class="material-symbols-outlined" style="font-size:16px">'+s.icon+'</span>'+s.phase+'<span style="margin-left:auto;font-size:0.72rem;opacity:0.7">'+s.step+' / '+SLIDES.length+'</span></div>' +
    '<div class="ss-title">'+s.title+'</div>' +
    '<div class="ss-subtitle">'+s.subtitle+'</div>' +
    loc +
    '<div class="ss-mock-wrap">'+renderMock(s)+'</div>' +
    '<div class="ss-usehd"><span class="material-symbols-outlined" style="font-size:18px;color:'+s.phaseColor+'">list_alt</span>くわしい使い方</div>' +
    '<div class="ss-points">' +
      s.points.map(function(p,i){ return '<div class="ss-point"><span class="ss-num" style="background:'+s.phaseColor+'">'+(i+1)+'</span><span class="ss-point-txt">'+p+'</span></div>'; }).join('') +
    '</div>' +
    '<div class="ss-tip" style="border-left:4px solid '+s.phaseColor+';background:'+s.phaseColor+'18"><span class="material-symbols-outlined" style="font-size:19px;color:'+s.phaseColor+';flex-shrink:0">lightbulb</span><span>'+s.tip+'</span></div>';
  el.scrollTop=0;
  var prev=document.getElementById('ss-prev'); if(prev) prev.style.opacity=idx===0?'0.3':'1';
  var nextBtn=document.getElementById('ss-next');
  if(nextBtn) nextBtn.innerHTML=idx===SLIDES.length-1?'<span class="material-symbols-outlined">close</span>':'<span class="material-symbols-outlined">arrow_forward</span>';
  renderDots();
}
function ssNext(){ if(_ssIdx>=SLIDES.length-1){ closeSlideshow(); return; } renderSlide(_ssIdx+1); }
function ssPrev(){ if(_ssIdx<=0) return; renderSlide(_ssIdx-1); }

// キーボード左右
document.addEventListener('keydown', function(e){
  var m=document.getElementById('ss-modal');
  if(!m || m.style.display==='none') return;
  if(e.key==='ArrowRight') ssNext();
  if(e.key==='ArrowLeft') ssPrev();
  if(e.key==='Escape') closeSlideshow();
});

// スワイプ
(function(){
  var startX=0,startY=0,swiping=false;
  document.addEventListener('touchstart', function(e){
    var modal=document.getElementById('ss-modal');
    if(!modal || !modal.classList.contains('is-active')) return;
    var content=document.getElementById('ss-content');
    if(content && content.contains(e.target)){ swiping=false; return; }
    startX=e.touches[0].clientX; startY=e.touches[0].clientY; swiping=true;
  }, {passive:true});
  document.addEventListener('touchend', function(e){
    var modal=document.getElementById('ss-modal');
    if(!modal || !modal.classList.contains('is-active') || !swiping) return;
    swiping=false;
    var dx=e.changedTouches[0].clientX-startX, dy=e.changedTouches[0].clientY-startY;
    if(Math.abs(dx)>Math.abs(dy) && Math.abs(dx)>45){ dx<0?ssNext():ssPrev(); }
  }, {passive:true});
})();

// スライド内画像のピンチ拡大
(function(){
  var scale=1,lastScale=1,startDist=0,imgEl=null;
  function getDist(t){ var dx=t[0].clientX-t[1].clientX,dy=t[0].clientY-t[1].clientY; return Math.sqrt(dx*dx+dy*dy); }
  document.addEventListener('touchstart', function(e){
    var modal=document.getElementById('ss-modal');
    if(!modal || !modal.classList.contains('is-active')) return;
    if(e.touches.length===2){ imgEl=document.querySelector('#ss-content img'); if(!imgEl) return; startDist=getDist(e.touches); lastScale=scale; }
  }, {passive:true});
  document.addEventListener('touchmove', function(e){
    var modal=document.getElementById('ss-modal');
    if(!modal || !modal.classList.contains('is-active')) return;
    if(e.touches.length===2 && imgEl){ scale=Math.min(4,Math.max(1,lastScale*(getDist(e.touches)/startDist))); imgEl.style.transformOrigin='center center'; imgEl.style.transform='scale('+scale+')'; imgEl.style.transition='none'; imgEl.style.zIndex='10'; }
  }, {passive:true});
  document.addEventListener('touchend', function(e){
    var modal=document.getElementById('ss-modal');
    if(!modal || !modal.classList.contains('is-active')) return;
    if(imgEl && e.touches.length<2 && scale<1.1){ scale=1; imgEl.style.transform='scale(1)'; imgEl.style.transition='transform 0.25s'; }
  }, {passive:true});
})();

// ガイドページ全体のピンチ拡大
(function(){
  var scale=1,lastScale=1,startDist=0,originX=0.5,originY=0;
  function getDist(t){ var dx=t[0].clientX-t[1].clientX,dy=t[0].clientY-t[1].clientY; return Math.sqrt(dx*dx+dy*dy); }
  function getMid(t){ return {x:(t[0].clientX+t[1].clientX)/2,y:(t[0].clientY+t[1].clientY)/2}; }
  document.addEventListener('touchstart', function(e){
    var modal=document.getElementById('ss-modal');
    if(modal && modal.classList.contains('is-active')) return;
    if(e.touches.length===2){ startDist=getDist(e.touches); lastScale=scale; var mid=getMid(e.touches); var el=document.querySelector('.gpad, .gd'); if(el){ var r=el.getBoundingClientRect(); originX=((mid.x-r.left)/r.width*100).toFixed(1)+'%'; originY=((mid.y-r.top)/r.height*100).toFixed(1)+'%'; } }
  }, {passive:true});
  document.addEventListener('touchmove', function(e){
    var modal=document.getElementById('ss-modal');
    if(modal && modal.classList.contains('is-active')) return;
    if(e.touches.length===2){ scale=Math.min(3.5,Math.max(1,lastScale*(getDist(e.touches)/startDist))); var el=document.querySelector('.gpad, .gd'); if(el){ el.style.transformOrigin=originX+' '+originY; el.style.transform='scale('+scale+')'; el.style.transition='none'; } }
  }, {passive:true});
  document.addEventListener('touchend', function(e){
    var modal=document.getElementById('ss-modal');
    if(modal && modal.classList.contains('is-active')) return;
    if(e.touches.length<2 && scale<1.08){ scale=1; var el=document.querySelector('.gpad, .gd'); if(el){ el.style.transform='scale(1)'; el.style.transition='transform 0.3s'; } }
  }, {passive:true});
  var lastTap=0;
  document.addEventListener('touchend', function(e){
    var modal=document.getElementById('ss-modal');
    if(modal && modal.classList.contains('is-active')) return;
    var now=(new Date()).getTime();
    if(now-lastTap<300 && e.touches.length===0){ scale=1; var el=document.querySelector('.gpad, .gd'); if(el){ el.style.transform='scale(1)'; el.style.transition='transform 0.25s'; } }
    lastTap=now;
  }, {passive:true});
})();
