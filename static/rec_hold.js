/* rec-hold-v1 — 録音の「まだ送っていないぶん」を端末の中に書き溜める保険
 *
 * ■ なぜ要るか
 *   担当者会議の録音は5分ごとに区切ってサーバーへ送っている。
 *   送るまでの最大5分ぶんはブラウザのメモリの中にしかなく、
 *   アプリごと落ちるとその5分は戻らない。過去に実際に失われたことがある。
 *
 * ■ どうしているか
 *   同じマイクの音を、2つの録音器で同時に録る。
 *     ① いままでどおりの録音器 … 5分たったら止めて、サーバーへ送る（送る中身は一切変えない）
 *     ② この保険の録音器      … 15秒ごとに小分けを出し、届くたびに端末の中へ書く
 *   ①が無事に送れたら、②の書き溜めは消す。
 *   落ちたときは②の残りが端末に残っているので、次に開いたとき拾って文字起こしできる。
 *
 * ■ 確かめてあること（2026-08-25・Chromium で実測）
 *   ・同じ音声を2つの録音器で同時に録れる（どちらもエラーなし）
 *   ・①の出力は、小分けを使わない今までのものと同じ（長さの情報も入る）
 *   ・②の小分けは、全部つなげても、途中までしか無くても、音声として読める
 *
 * ■ 触ると壊れる場所
 *   ・②は「保険」であって「正本」ではない。①が失敗したときの代わりに使うだけ。
 *     ②を送る側にしないこと（つなげたものには長さの情報が入らない）。
 *   ・②が作れない端末では、黙って保険なしで動く。録音そのものは絶対に止めない。
 *   ・書き溜めを消すのは「①が成功したとき」だけ。送信失敗のまま消さないこと。
 */
(function () {
  'use strict';

  var DB_NAME = 'tasukaru_rec_hold';
  var DB_VER = 1;
  var STORE = 'parts';
  var SLICE_MS = 15000;          // 15秒ごとに小分けを受け取る
  var HOLD_BPS = 32000;          // 保険なので軽めに（文字起こしには十分）

  var st = {
    on: false, rec: null, cxt: null, sid: null, chunk: 0, label: '',
    failed: false, stopped: false
  };

  // ★録音器を止めても、最後の小分けは少し遅れて届く。
  //   そのとき番号を「いまの区切り」から取ると、前の区切りの尻尾が
  //   次の区切りの先頭として書かれ、音声の見出しが無い状態になって読めなくなる。
  //   （2026-08-25 に実際にこれで壊れた）
  //   だから番号は録音器ごとに持たせる。下の cxt がそれ。
  var sealed = {};   // 送信済みの区切り。遅れて届いた小分けは捨てる

  // ---------- IndexedDB（端末の中の保管庫） ----------

  function openDB() {
    return new Promise(function (res, rej) {
      var req;
      try { req = indexedDB.open(DB_NAME, DB_VER); }
      catch (e) { rej(e); return; }
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: 'key' });
        }
      };
      req.onsuccess = function () { res(req.result); };
      req.onerror = function () { rej(req.error); };
    });
  }

  function tx(mode, fn) {
    return openDB().then(function (db) {
      return new Promise(function (res, rej) {
        var t = db.transaction(STORE, mode);
        var s = t.objectStore(STORE);
        var out = fn(s);
        t.oncomplete = function () { db.close(); res(out && out.value !== undefined ? out.value : out); };
        t.onerror = function () { db.close(); rej(t.error); };
        t.onabort = function () { db.close(); rej(t.error); };
      });
    });
  }

  function pad(n) { return ('000' + n).slice(-4); }

  function putPart(sid, chunk, seq, blob, mime, label, sliceMs) {
    if (st.stopped) return Promise.resolve();              // 全部捨てたあと
    if (sealed[sid + '|' + chunk]) return Promise.resolve(); // 送信済みの区切り
    var key = sid + '|' + pad(chunk) + '|' + pad(seq);
    return tx('readwrite', function (s) {
      s.put({ key: key, sid: sid, chunk: chunk, seq: seq,
              blob: blob, mime: mime, label: label || '',
              sliceMs: sliceMs || SLICE_MS, ts: Date.now() });
    });
  }

  function allParts() {
    return tx('readonly', function (s) {
      var box = { value: [] };
      var req = s.openCursor();
      req.onsuccess = function () {
        var c = req.result;
        if (!c) return;
        box.value.push(c.value);
        c.continue();
      };
      return box;
    });
  }

  function deleteChunk(sid, chunk) {
    return tx('readwrite', function (s) {
      var req = s.openCursor();
      req.onsuccess = function () {
        var c = req.result;
        if (!c) return;
        if (c.value.sid === sid && c.value.chunk === chunk) c.delete();
        c.continue();
      };
    });
  }

  function clearAll() {
    // ★「全部捨てる」なので、遅れて届く小分けも以後は書かない。
    //   これを立てないと、消した直後に尻尾が書き戻されて残る。
    st.stopped = true;
    sealed = {};
    return tx('readwrite', function (s) { s.clear(); });
  }

  // ---------- 保険の録音器 ----------

  /** 5分ぶんの区切りが1つ始まるたびに呼ぶ。stream は録音器①と同じもの。 */
  function begin(opts) {
    opts = opts || {};
    stopRec();                       // 前の区切りぶんが残っていれば止める
    st.sid = opts.sessionId || st.sid;
    st.chunk = (typeof opts.chunkIndex === 'number') ? opts.chunkIndex : st.chunk;
    st.label = opts.label || st.label;
    st.stopped = false;
    if (!opts.stream || !window.MediaRecorder || !window.indexedDB) { st.failed = true; return false; }
    try {
      var r;
      try { r = new MediaRecorder(opts.stream, { audioBitsPerSecond: HOLD_BPS }); }
      catch (e1) { r = new MediaRecorder(opts.stream); }   // 指定が通らない端末向け
      // ★この録音器だけの番号。遅れて届く最後の小分けも、正しい区切りに書かれる。
      var cxt = { sid: st.sid, chunk: st.chunk, label: st.label, seq: 0,
                  mime: r.mimeType || 'audio/webm', sliceMs: opts.sliceMs || SLICE_MS };
      r.ondataavailable = function (e) {
        if (!e.data || !e.data.size) return;
        putPart(cxt.sid, cxt.chunk, cxt.seq++, e.data, cxt.mime, cxt.label, cxt.sliceMs)
          .catch(function (err) {
            if (!st.failed) console.log('[rec-hold] 端末への書き溜めに失敗: ' + err);
            st.failed = true;
          });
      };
      r.onerror = function (e) {
        console.log('[rec-hold] 保険の録音器でエラー: ' + (e && e.error));
        st.failed = true;
      };
      r.start(opts.sliceMs || SLICE_MS);   // sliceMs は試験用の上書き。ふだんは指定しない
      st.rec = r;
      st.cxt = cxt;
      st.on = true;
      return true;
    } catch (e) {
      // ★保険が作れない端末でも、録音そのものは絶対に止めない
      console.log('[rec-hold] 保険の録音器を作れませんでした（保険なしで続行）: ' + e);
      st.failed = true;
      st.rec = null;
      st.on = false;
      return false;
    }
  }

  function stopRec() {
    try { if (st.rec && st.rec.state !== 'inactive') st.rec.stop(); } catch (e) {}
    st.rec = null;
    st.on = false;
  }

  /** その区切りがサーバーへ無事に送れた。書き溜めを消してよい。 */
  function uploaded(chunkIndex) {
    var sid = st.sid;
    if (!sid) return Promise.resolve();
    // ★先に「もう受け付けない」印を付ける。消したあとに遅れて届いた小分けが
    //   書き戻され、送信済みなのに残っているように見えるのを防ぐ。
    sealed[sid + '|' + chunkIndex] = 1;
    return deleteChunk(sid, chunkIndex).catch(function (e) {
      console.log('[rec-hold] 書き溜めの削除に失敗: ' + e);
    });
  }

  /** 録音を完全に終える。最後の区切りの尻尾は書かれる（まだ送っていないため）。 */
  function finish() {
    stopRec();
  }

  // ---------- 残っているものを拾う ----------

  /** 端末に残っている書き溜めを、区切りごとにまとめて返す。 */
  function pending() {
    return allParts().then(function (rows) {
      var map = {};
      (rows || []).forEach(function (r) {
        var k = r.sid + '|' + r.chunk;
        if (!map[k]) map[k] = { sid: r.sid, chunk: r.chunk, label: r.label, ts: r.ts, parts: [], bytes: 0 };
        map[k].parts.push(r);
        map[k].bytes += (r.blob && r.blob.size) || 0;
        if (r.ts > map[k].ts) map[k].ts = r.ts;
      });
      var list = Object.keys(map).map(function (k) {
        var g = map[k];
        g.parts.sort(function (a, b) { return a.seq - b.seq; });
        g.blob = new Blob(g.parts.map(function (p) { return p.blob; }),
                          { type: (g.parts[0] && g.parts[0].mime) || 'audio/webm' });
        var sms = (g.parts[0] && g.parts[0].sliceMs) || SLICE_MS;
        g.seconds = Math.round(g.parts.length * (sms / 1000));
        delete g.parts;
        return g;
      });
      list.sort(function (a, b) { return a.ts - b.ts; });
      return list;
    }).catch(function (e) {
      console.log('[rec-hold] 残りの確認に失敗: ' + e);
      return [];
    });
  }

  window.recHold = {
    begin: begin,
    uploaded: uploaded,
    finish: finish,
    pending: pending,
    drop: deleteChunk,
    clearAll: clearAll,
    sliceMs: SLICE_MS,
    isFailed: function () { return st.failed; },
    isOn: function () { return st.on; }
  };
})();
