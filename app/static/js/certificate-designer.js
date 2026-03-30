/**
 * Certificate visual designer — Fabric.js canvas, cert_style v2 freeform JSON.
 * Coordinates: PDF points, origin bottom-left on save; Fabric uses top-left (Y down).
 */
(function () {
  var bootEl = document.getElementById("cert-designer-bootstrap");
  var canvasEl = document.getElementById("cert-designer-canvas");
  if (!bootEl || !canvasEl || typeof fabric === "undefined") return;

  var bootstrap = {};
  try {
    bootstrap = JSON.parse((bootEl.textContent || "{}").trim());
  } catch (e) {
    console.error("certificate-designer: invalid bootstrap JSON", e);
    window.alert("Certificate designer failed to load configuration. Reload the page.");
    return;
  }
  var eventId = bootstrap.eventId;
  var templateId = bootstrap.templateId;
  var designerSaveUrl =
    bootstrap.saveUrl ||
    bootstrap.designerSaveUrl ||
    (eventId != null ? "/admin/events/" + eventId + "/certificate/designer" : null) ||
    (templateId != null
      ? "/admin/certificate-templates/" + templateId + "/certificate/designer"
      : null);
  var designerLegacyUrl =
    bootstrap.legacyConvertUrl ||
    bootstrap.designerLegacyUrl ||
    (eventId != null ? "/admin/events/" + eventId + "/certificate/legacy-to-freeform" : null) ||
    (templateId != null
      ? "/admin/certificate-templates/" + templateId + "/certificate/legacy-to-freeform"
      : null);
  var aiGenerateUrl = bootstrap.aiGenerateUrl || "/admin/certificate-ai/generate-template";
  if (!designerSaveUrl || !designerLegacyUrl) {
    console.error("certificate-designer: missing saveUrl/legacyConvertUrl (or legacy designer* keys) in bootstrap");
    return;
  }
  var doc = bootstrap.initialStyle || {};

  var PDF_W = (doc.page && doc.page.widthPt) || 842;
  var PDF_H = (doc.page && doc.page.heightPt) || 595;

  var VARIABLE_OPTS = [
    { v: "static", l: "Static text" },
    { v: "attendee_name", l: "Attendee name" },
    { v: "event_name", l: "Event name" },
    { v: "event_date", l: "Event date" },
    { v: "venue", l: "Venue (plain)" },
    { v: "venue_line", l: "Venue line" },
    { v: "cert_id", l: "Certificate ID" },
    { v: "booking_ref", l: "Booking ref" },
    { v: "title_text", l: "Title (cert title)" },
    { v: "subtitle_text", l: "Subtitle" },
    { v: "footer_text", l: "Footer text" },
    { v: "signer_name", l: "Signer name" },
    { v: "signer_designation", l: "Signer designation" },
    { v: "event_session_title", l: "Session title (quoted)" },
    { v: "attending_line", l: "Attending line" },
    { v: "brand_text", l: "Brand (TECHTREK)" },
    { v: "details_line", l: "Details (speaker/date)" },
    { v: "cert_id_line", l: "Certificate ID line" },
    { v: "speaker_name", l: "Speaker" },
  ];

  function uid() {
    return "L" + Math.random().toString(36).slice(2, 10);
  }

  function fabricTopFromPdfY(yPt, heightPt) {
    return PDF_H - yPt - heightPt;
  }

  function pdfYFromFabricTop(top, heightPt) {
    return PDF_H - top - heightPt;
  }

  function snap(v, g) {
    if (!g) return v;
    return Math.round(v / g) * g;
  }

  /** Sample strings for the editor only — variable fields still save with text: "" for PDF resolution. */
  function previewSampleForVariable(v) {
    var key = String(v || "static").toLowerCase();
    var samples = {
      static: "Text",
      attendee_name: "Jordan A. Sample",
      event_name: "Annual Tech Summit 2026",
      event_date: "30 March 2026",
      venue: "Grand Hall, City",
      venue_line: "Venue: Grand Hall, City",
      cert_id: "CERT-ABC123",
      booking_ref: "ABC123",
      title_text: "CERTIFICATE OF ATTENDANCE",
      subtitle_text: "This certificate is proudly presented to",
      footer_text: "© 2026 TechTrek. All rights reserved.",
      signer_name: "Dr. Priya Sharma",
      signer_designation: "Program Director",
      event_session_title: "“Session / event title”",
      attending_line: "for attending the session",
      brand_text: "TECHTREK",
      details_line: "Speaker: …    Date: 30 March 2026",
      cert_id_line: "Certificate ID: CERT-ABC123",
      speaker_name: "Speaker Name",
    };
    return samples[key] || "[" + key + "]";
  }

  /** Map cert_style font key to a CSS font stack Fabric can render. */
  function fontKeyToFabricFamily(key) {
    var k = String(key || "arial").toLowerCase();
    var map = {
      arial: "Arial, Helvetica, sans-serif",
      georgia: "Georgia, serif",
      times: "'Times New Roman', Times, serif",
      verdana: "Verdana, Geneva, sans-serif",
      trebuchet: "'Trebuchet MS', Helvetica, sans-serif",
      courier: "'Courier New', Courier, monospace",
      comic: "'Comic Sans MS', cursive",
      calibri: "Calibri, 'Segoe UI', sans-serif",
      palatino: "Palatino, 'Palatino Linotype', serif",
      candara: "Candara, Verdana, sans-serif",
    };
    return map[k] || map.arial;
  }

  var canvas = new fabric.Canvas("cert-designer-canvas", {
    width: PDF_W,
    height: PDF_H,
    preserveObjectStacking: true,
    selection: true,
  });
  canvas.backgroundColor = "#ffffff";

  function mmToPt(mmVal) {
    return (mmVal * 72) / 25.4;
  }

  function chromeBaseProps() {
    return {
      selectable: false,
      evented: false,
      certChrome: true,
      hoverCursor: "default",
      excludeFromExport: true,
      objectCaching: false,
    };
  }

  function getChromeColors() {
    var primary = (doc.border_color_primary && String(doc.border_color_primary).trim()) || "#0e7490";
    var gold = (doc.border_color_secondary && String(doc.border_color_secondary).trim()) || "#d4a853";
    var accent = (doc.border_color_tertiary && String(doc.border_color_tertiary).trim()) || "#00d4ff";
    return { border: primary, gold: gold, accent: accent };
  }

  function removeCertChrome() {
    var objs = canvas.getObjects().filter(function (o) {
      return o.certChrome;
    });
    objs.forEach(function (o) {
      canvas.remove(o);
    });
  }

  function removePageBg() {
    canvas.getObjects().filter(function (o) {
      return o.certPageBg;
    }).forEach(function (o) {
      canvas.remove(o);
    });
  }

  /** Match _draw_freeform_background in certificate.py (ReportLab bottom-left for draw_x, draw_y). */
  function computeFreeformBgLayout(iw, ih, pageW, pageH, bgMode, ox, oy) {
    var draw_x;
    var draw_y;
    var draw_w;
    var draw_h;
    if (bgMode === "stretch") {
      draw_w = pageW;
      draw_h = pageH;
      draw_x = 0;
      draw_y = 0;
    } else {
      var scale =
        bgMode === "contain"
          ? Math.min(pageW / iw, pageH / ih)
          : Math.max(pageW / iw, pageH / ih);
      draw_w = iw * scale;
      draw_h = ih * scale;
      draw_x = (pageW - draw_w) / 2;
      draw_y = (pageH - draw_h) / 2;
    }
    draw_x += ox || 0;
    draw_y += oy || 0;
    return { draw_x: draw_x, draw_y: draw_y, draw_w: draw_w, draw_h: draw_h };
  }

  var pageBgLoadToken = 0;

  function drawPageBackground() {
    removePageBg();
    var urlEl = document.getElementById("cert-dz-page-bg-url");
    var url = urlEl ? (urlEl.value || "").trim() : "";
    if (!url) {
      canvas.requestRenderAll();
      return;
    }
    var bgMode = (document.getElementById("cert-dz-bg-size").value || "cover").toLowerCase();
    var ox = parseFloat(doc.bg_offset_x) || 0;
    var oy = parseFloat(doc.bg_offset_y) || 0;
    var myTok = ++pageBgLoadToken;
    var imgOpts = {};
    if (/^https?:\/\//i.test(url)) {
      imgOpts.crossOrigin = "anonymous";
    }
    fabric.Image.fromURL(
      url,
      function (img, isError) {
        if (myTok !== pageBgLoadToken) return;
        if (isError || !img) return;
        var cur = urlEl ? (urlEl.value || "").trim() : "";
        if (cur !== url) return;
        var iw = img.width || 1;
        var ih = img.height || 1;
        var L = computeFreeformBgLayout(iw, ih, PDF_W, PDF_H, bgMode, ox, oy);
        var fabricTop = PDF_H - L.draw_y - L.draw_h;
        img.set({
          left: L.draw_x,
          top: fabricTop,
          scaleX: L.draw_w / iw,
          scaleY: L.draw_h / ih,
          selectable: false,
          evented: false,
          certPageBg: true,
          excludeFromExport: true,
          objectCaching: false,
          hoverCursor: "default",
        });
        canvas.add(img);
        canvas.sendToBack(img);
        canvas.requestRenderAll();
      },
      imgOpts
    );
  }

  function uploadCertImage(file, onUrl) {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      window.alert("File too large (max 5 MB)");
      return;
    }
    var fd = new FormData();
    fd.append("image", file);
    var csrfEl = document.querySelector('input[name="csrf_token"]');
    if (csrfEl) fd.append("csrf_token", csrfEl.value);
    fetch("/admin/upload-image", { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (data.url) onUrl(data.url);
        else window.alert(data.error || "Upload failed");
      })
      .catch(function (e) {
        window.alert("Upload failed: " + (e.message || e));
      });
  }

  /**
   * Non-selectable Fabric shapes approximating certificate.py border styles (PDF uses bottom-left origin;
   * we use top-left matching the rest of this editor).
   */
  function drawPageChrome() {
    removeCertChrome();
    var style = (document.getElementById("cert-dz-border-style").value || "classic").toLowerCase();
    var bw = Math.max(0.25, parseFloat(document.getElementById("cert-dz-border-width").value) || 1);
    var clr = getChromeColors();
    var W = PDF_W;
    var H = PDF_H;
    var c0 = chromeBaseProps();
    var list = [];

    function rectStroke(left, top, w, h, stroke, sw, rx, ry) {
      var o = {
        left: left,
        top: top,
        width: w,
        height: h,
        fill: "transparent",
        stroke: stroke,
        strokeWidth: Math.max(0.25, sw),
        originX: "left",
        originY: "top",
      };
      if (rx != null) {
        o.rx = rx;
        o.ry = ry != null ? ry : rx;
      }
      list.push(new fabric.Rect(Object.assign({}, o, c0)));
    }

    function rectFill(left, top, w, h, fill) {
      list.push(
        new fabric.Rect(
          Object.assign(
            {
              left: left,
              top: top,
              width: w,
              height: h,
              fill: fill,
              stroke: null,
              originX: "left",
              originY: "top",
            },
            c0
          )
        )
      );
    }

    function linePts(x1, y1, x2, y2, stroke, sw) {
      list.push(
        new fabric.Line([x1, y1, x2, y2], Object.assign({ stroke: stroke, strokeWidth: Math.max(0.25, sw) }, c0))
      );
    }

    /**
     * Stroke is centered on the path in Fabric. Inset by half stroke width so the *outer* edge of the
     * stroke sits `marginPt` from the page edge (matches ReportLab / PDF appearance and keeps the frame centered).
     */
    function frameAtMargin(marginPt, strokeW, strokeColor, rx, ry) {
      var sw = Math.max(0.25, strokeW);
      var half = sw / 2;
      rectStroke(
        marginPt + half,
        marginPt + half,
        W - 2 * marginPt - sw,
        H - 2 * marginPt - sw,
        strokeColor,
        sw,
        rx,
        ry
      );
    }

    /**
     * Thick stroked roundRect + left/top origin is asymmetric in Fabric/canvas2d. Center the path on the
     * page so the frame stays visually balanced (matches PDF intent for the “modern” border).
     */
    function roundedFrameCentered(marginPt, strokeW, strokeColor, rxRaw) {
      var sw = Math.max(0.25, strokeW);
      var iw = W - 2 * marginPt - sw;
      var ih = H - 2 * marginPt - sw;
      var rx = rxRaw != null ? rxRaw : 0;
      var ry = rx;
      var maxR = Math.min(iw, ih) / 2 - 0.5;
      if (rx > maxR) {
        rx = Math.max(0, maxR);
        ry = rx;
      }
      list.push(
        new fabric.Rect(
          Object.assign(
            {
              left: W / 2,
              top: H / 2,
              originX: "center",
              originY: "center",
              width: iw,
              height: ih,
              rx: rx,
              ry: ry,
              fill: "transparent",
              stroke: strokeColor,
              strokeWidth: sw,
            },
            c0
          )
        )
      );
    }

    if (style === "none") {
      canvas.requestRenderAll();
      return;
    }

    if (style === "classic") {
      var m1 = mmToPt(10);
      var m2 = mmToPt(15);
      var m3 = mmToPt(20);
      frameAtMargin(m1, 2.5 * bw, clr.border);
      frameAtMargin(m2, 0.8 * bw, clr.gold);
      frameAtMargin(m3, 0.5 * bw, clr.accent);
      var cap = Math.max(mmToPt(3), 9 * mmToPt(1) * bw);
      var corners = [
        [m1, m1],
        [W - m1, m1],
        [m1, H - m1],
        [W - m1, H - m1],
      ];
      corners.forEach(function (pt) {
        var cx = pt[0];
        var cy = pt[1];
        rectFill(cx - cap, cy - cap, 2 * cap, 2 * cap, clr.gold);
        rectStroke(cx - cap, cy - cap, 2 * cap, 2 * cap, clr.border, 0.5 * bw);
        var ds = cap * 0.62;
        list.push(
          new fabric.Polygon(
            [
              { x: 0, y: -ds },
              { x: ds, y: 0 },
              { x: 0, y: ds },
              { x: -ds, y: 0 },
            ],
            Object.assign(
              {
                left: cx,
                top: cy,
                fill: clr.border,
                stroke: null,
                originX: "center",
                originY: "center",
              },
              c0
            )
          )
        );
        list.push(
          new fabric.Circle(
            Object.assign(
              {
                left: cx,
                top: cy,
                radius: cap * 0.22,
                fill: clr.gold,
                stroke: null,
                originX: "center",
                originY: "center",
              },
              c0
            )
          )
        );
      });
    } else if (style === "modern") {
      var mg = mmToPt(10);
      var rx = mmToPt(12);
      roundedFrameCentered(mg, Math.min(16 * bw, 22), clr.border, rx);
      var inner = mg + 8;
      var rx2 = mmToPt(10);
      roundedFrameCentered(inner, 1.25 * bw, clr.accent, rx2);
    } else if (style === "elegant") {
      var e1 = mmToPt(10);
      var e2 = mmToPt(21);
      var rxo = mmToPt(4);
      var rxi = mmToPt(2);
      frameAtMargin(e1, 0.9 * bw, clr.border, rxo, rxo);
      frameAtMargin(e2, 0.5 * bw, clr.accent, rxi, rxi);
      var arm = Math.max(mmToPt(2), 7 * mmToPt(1) * bw);
      var ec = [
        [e1, e1],
        [W - e1, e1],
        [e1, H - e1],
        [W - e1, H - e1],
      ];
      ec.forEach(function (pt) {
        var cx = pt[0];
        var cy = pt[1];
        linePts(cx - arm, cy, cx + arm, cy, clr.accent, 0.6 * bw);
        linePts(cx, cy - arm, cx, cy + arm, clr.accent, 0.6 * bw);
      });
    } else if (style === "minimal") {
      var mar = mmToPt(14);
      var barH = mmToPt(5) * bw;
      rectFill(mar, mar, W - 2 * mar, barH, clr.border);
      rectFill(mar, H - mar - barH, W - 2 * mar, barH, clr.border);
      linePts(mar, H - mar - mmToPt(2), W - mar, H - mar - mmToPt(2), clr.accent, 0.5 * bw);
      linePts(mar, mar + barH - mmToPt(2), W - mar, mar + barH - mmToPt(2), clr.accent, 0.5 * bw);
    } else if (style === "ornate") {
      var o1 = mmToPt(10);
      var o2 = mmToPt(14);
      var o3 = mmToPt(18);
      frameAtMargin(o1, 2 * bw, clr.border, mmToPt(5), mmToPt(5));
      frameAtMargin(o2, 1 * bw, clr.gold, mmToPt(4), mmToPt(4));
      frameAtMargin(o3, 0.5 * bw, clr.accent, mmToPt(3), mmToPt(3));
    } else {
      var m = mmToPt(12);
      frameAtMargin(m, 1.5 * bw, clr.border);
    }

    if (typeof canvas.insertAt === "function") {
      list.forEach(function (obj, idx) {
        canvas.insertAt(obj, idx);
      });
    } else {
      list.forEach(function (obj) {
        canvas.add(obj);
      });
      for (var ci = list.length - 1; ci >= 0; ci--) {
        canvas.sendToBack(list[ci]);
      }
    }
    canvas.requestRenderAll();
  }

  function syncDocPageFieldsFromForm() {
    doc.border_style = document.getElementById("cert-dz-border-style").value;
    doc.border_width = parseFloat(document.getElementById("cert-dz-border-width").value) || 1;
    doc.bg_size = document.getElementById("cert-dz-bg-size").value;
    var pbg = document.getElementById("cert-dz-page-bg-url");
    if (pbg) doc.background_image_url = (pbg.value || "").trim();
  }

  var grid = 5;
  var history = [];
  var histPtr = -1;

  function cloneDoc() {
    return JSON.parse(JSON.stringify(doc));
  }

  function pushHistory() {
    var snapJson = JSON.stringify(serializeDocument());
    if (histPtr >= 0 && history[histPtr] === snapJson) return;
    history = history.slice(0, histPtr + 1);
    history.push(snapJson);
    histPtr = history.length - 1;
    if (history.length > 40) {
      history.shift();
      histPtr--;
    }
  }

  function applyHistory(idx) {
    if (idx < 0 || idx >= history.length) return;
    histPtr = idx;
    var o = JSON.parse(history[idx]);
    loadDocument(o);
  }

  function serializeObject(obj, zIndex) {
    var t = obj.certLayerType || "text";
    var w = obj.getScaledWidth();
    var h = obj.getScaledHeight();
    var left = obj.left;
    var top = obj.top;
    var rot = obj.angle || 0;
    var yPt = pdfYFromFabricTop(top, h);
    var xPt = left;

    if (t === "text") {
      var varKey = (obj.variable || "static").toLowerCase();
      var txt = "";
      if (varKey === "static") {
        txt = "";
        if (obj.type === "textbox" || obj.type === "i-text" || obj.type === "text") {
          txt = obj.text || "";
        }
      }
      var fontSize = 16;
      var fontFamily = "arial";
      var fill = "#0a1628";
      var textAlign = "left";
      var underline = false;
      if (obj.type === "textbox" || obj.type === "i-text" || obj.type === "text") {
        fontSize = obj.fontSize || 16;
        fontFamily = (obj.fontFamily || "Arial").toLowerCase().replace(/\s/g, "");
        if (fontFamily.indexOf("times") >= 0) fontFamily = "times";
        if (fontFamily.indexOf("georgia") >= 0) fontFamily = "georgia";
        if (fontFamily.indexOf("verdana") >= 0) fontFamily = "verdana";
        if (fontFamily.indexOf("courier") >= 0) fontFamily = "courier";
        if (fontFamily.indexOf("calibri") >= 0) fontFamily = "calibri";
        if (fontFamily === "arial" || !fontFamily) fontFamily = "arial";
        fill = typeof obj.fill === "string" ? obj.fill : "#0a1628";
        textAlign = obj.textAlign || "left";
        underline = !!obj.underline;
      }
      return {
        id: obj.layerId || uid(),
        type: "text",
        zIndex: zIndex,
        variable: varKey,
        text: txt,
        xPt: xPt,
        yPt: yPt,
        widthPt: w,
        heightPt: h,
        rotation: rot,
        font: fontFamily,
        fontSize: fontSize,
        color: fill,
        bold: !!obj.fontWeight && obj.fontWeight === "bold",
        italic: !!obj.fontStyle && obj.fontStyle === "italic",
        align: textAlign,
        underline: underline,
      };
    }

    if (t === "image") {
      return {
        id: obj.layerId || uid(),
        type: "image",
        zIndex: zIndex,
        imageRole: obj.imageRole || "custom",
        url: obj.imageUrl || "",
        xPt: xPt,
        yPt: yPt,
        widthPt: w,
        heightPt: h,
        rotation: rot,
      };
    }

    if (t === "qr") {
      return {
        id: obj.layerId || uid(),
        type: "qr",
        zIndex: zIndex,
        xPt: xPt,
        yPt: yPt,
        widthPt: w,
        heightPt: h,
        rotation: rot,
        showCaption: obj.showCaption !== false,
      };
    }

    if (t === "line") {
      var x2Pt = xPt + w;
      var y2Pt = yPt;
      return {
        id: obj.layerId || uid(),
        type: "line",
        zIndex: zIndex,
        xPt: xPt,
        yPt: yPt,
        x2Pt: x2Pt,
        y2Pt: y2Pt,
        lineWidth: obj.strokeWidth || 1.5,
        color: typeof obj.fill === "string" ? obj.fill : obj.stroke || "#0a1628",
        rotation: rot,
      };
    }

    if (t === "rect") {
      return {
        id: obj.layerId || uid(),
        type: "rect",
        zIndex: zIndex,
        xPt: xPt,
        yPt: yPt,
        widthPt: w,
        heightPt: h,
        rotation: rot,
        fillColor: obj.fill && typeof obj.fill === "string" && obj.fill !== "transparent" ? obj.fill : "",
        strokeColor: obj.stroke && typeof obj.stroke === "string" ? obj.stroke : "#64748b",
        strokeWidth: obj.strokeWidth || 1,
      };
    }

    return null;
  }

  function serializeDocument() {
    var out = cloneDoc();
    out.version = 2;
    out.layout = "freeform";
    out.page = { widthPt: PDF_W, heightPt: PDF_H };
    var borderStyleEl = document.getElementById("cert-dz-border-style");
    var borderWidthEl = document.getElementById("cert-dz-border-width");
    var bgSizeEl = document.getElementById("cert-dz-bg-size");
    out.border_style = borderStyleEl ? borderStyleEl.value : "classic";
    out.border_width = borderWidthEl ? parseFloat(borderWidthEl.value) || 1 : 1;
    out.bg_size = bgSizeEl ? bgSizeEl.value : "cover";
    var bgUrlEl = document.getElementById("cert-dz-page-bg-url");
    out.background_image_url = bgUrlEl ? (bgUrlEl.value || "").trim() : "";
    var layers = [];
    canvas.getObjects().forEach(function (obj, i) {
      if (obj.certChrome) return;
      if (obj.certPageBg) return;
      var L = serializeObject(obj, i);
      if (L) layers.push(L);
    });
    out.layers = layers;
    return out;
  }

  function addTextLayer(variable, sampleText) {
    var tid = uid();
    var v = variable || "static";
    var display = sampleText;
    if (display == null || display === "") {
      display = v === "static" ? "Your text" : previewSampleForVariable(v);
    }
    var tb = new fabric.Textbox(display, {
      left: 120,
      top: fabricTopFromPdfY(250, 40),
      width: 500,
      fontSize: 24,
      fontFamily: fontKeyToFabricFamily("arial"),
      fill: "#0a1628",
      originX: "left",
      originY: "top",
    });
    tb.layerId = tid;
    tb.certLayerType = "text";
    tb.variable = v;
    canvas.add(tb);
    canvas.setActiveObject(tb);
    canvas.requestRenderAll();
    pushHistory();
  }

  function addImagePlaceholder(role, url) {
    var iid = uid();
    var w = role === "signature" ? 120 : 100;
    var h = role === "signature" ? 50 : 40;
    var rect = new fabric.Rect({
      left: role === "signature" ? 50 : PDF_W / 2 - w / 2,
      top: fabricTopFromPdfY(role === "signature" ? 100 : 480, h),
      width: w,
      height: h,
      fill: "#f1f5f9",
      stroke: "#94a3b8",
      strokeWidth: 1,
      originX: "left",
      originY: "top",
    });
    rect.layerId = iid;
    rect.certLayerType = "image";
    rect.imageRole = role || "custom";
    rect.imageUrl = url || "";
    var label = new fabric.Text(
      role === "logo" ? "Logo" : role === "signature" ? "Signature" : "Image",
      {
        fontSize: 11,
        fill: "#64748b",
        originX: "center",
        originY: "center",
        left: rect.left + w / 2,
        top: rect.top + h / 2,
      }
    );
    var grp = new fabric.Group([rect, label], {
      left: rect.left,
      top: rect.top,
      originX: "left",
      originY: "top",
    });
    grp.layerId = iid;
    grp.certLayerType = "image";
    grp.imageRole = role || "custom";
    grp.imageUrl = url || "";
    canvas.add(grp);
    canvas.setActiveObject(grp);
    canvas.requestRenderAll();
    if ((url || "").trim()) {
      hydrateCertImageLayer(grp);
    }
    pushHistory();
  }

  var _certDzImageHydrateTok = {};

  function canvasIndexOf(obj) {
    return canvas.getObjects().indexOf(obj);
  }

  function replaceCertImageGroup(oldG, newG) {
    var ix = canvasIndexOf(oldG);
    if (ix < 0) ix = canvas.getObjects().length;
    canvas.remove(oldG);
    if (typeof canvas.insertAt === "function") {
      canvas.insertAt(newG, ix);
    } else {
      canvas.add(newG);
    }
  }

  function makeImagePlaceholderParts(innerW, innerH, role) {
    var rect = new fabric.Rect({
      left: 0,
      top: 0,
      width: innerW,
      height: innerH,
      fill: "#f1f5f9",
      stroke: "#94a3b8",
      strokeWidth: 1,
      originX: "left",
      originY: "top",
    });
    var glabel =
      role === "logo" ? "Logo" : role === "signature" ? "Signature" : "Image";
    var lt = new fabric.Text(glabel, {
      fontSize: 11,
      fill: "#64748b",
      originX: "center",
      originY: "center",
      left: innerW / 2,
      top: innerH / 2,
    });
    return [rect, lt];
  }

  function buildCertImageGroup(parts, layout) {
    var g = new fabric.Group(parts, {
      left: layout.left,
      top: layout.top,
      originX: layout.originX || "left",
      originY: layout.originY || "top",
      angle: layout.angle || 0,
      scaleX: layout.scaleX != null ? layout.scaleX : 1,
      scaleY: layout.scaleY != null ? layout.scaleY : 1,
    });
    g.layerId = layout.layerId;
    g.certLayerType = "image";
    g.imageRole = layout.imageRole || "custom";
    g.imageUrl = layout.imageUrl != null ? layout.imageUrl : "";
    if (layout._certDzLoadedUrl != null) g._certDzLoadedUrl = layout._certDzLoadedUrl;
    return g;
  }

  function scaleInnerImageToGroupBounds(grp) {
    var inner = grp.getObjects && grp.getObjects();
    if (!inner || inner.length !== 1 || inner[0].type !== "image") return false;
    var fi = inner[0];
    var L2 = captureImageGroupLayout(grp);
    var iw0 = fi.width || 1;
    var ih0 = fi.height || 1;
    fi.set({ scaleX: L2.gw / iw0, scaleY: L2.gh / ih0 });
    grp.set({ dirty: true });
    if (typeof grp.addWithUpdate === "function") grp.addWithUpdate(fi);
    return true;
  }

  function captureImageGroupLayout(grp) {
    var sx = Math.abs(grp.scaleX || 1) || 1;
    var sy = Math.abs(grp.scaleY || 1) || 1;
    return {
      left: grp.left,
      top: grp.top,
      originX: grp.originX || "left",
      originY: grp.originY || "top",
      angle: grp.angle || 0,
      scaleX: grp.scaleX || 1,
      scaleY: grp.scaleY || 1,
      layerId: grp.layerId,
      imageRole: grp.imageRole || "custom",
      imageUrl: grp.imageUrl || "",
      gw: grp.getScaledWidth(),
      gh: grp.getScaledHeight(),
      innerW: grp.getScaledWidth() / sx,
      innerH: grp.getScaledHeight() / sy,
    };
  }

  /**
   * Load bitmap for image layers so uploads / URLs show on canvas (PDF already drew from url).
   */
  function hydrateCertImageLayer(grp) {
    if (!grp || grp.certLayerType !== "image" || grp.type !== "group") return;
    var layout = captureImageGroupLayout(grp);
    var url = (layout.imageUrl || "").trim();
    var lid = layout.layerId;
    _certDzImageHydrateTok[lid] = (_certDzImageHydrateTok[lid] || 0) + 1;
    var myTok = _certDzImageHydrateTok[lid];

    if (!url) {
      var iw = Math.max(20, layout.innerW || 80);
      var ih = Math.max(16, layout.innerH || 40);
      var parts = makeImagePlaceholderParts(iw, ih, layout.imageRole);
      var newG = buildCertImageGroup(parts, {
        left: layout.left,
        top: layout.top,
        originX: layout.originX,
        originY: layout.originY,
        angle: layout.angle,
        scaleX: 1,
        scaleY: 1,
        layerId: layout.layerId,
        imageRole: layout.imageRole,
        imageUrl: "",
        _certDzLoadedUrl: "",
      });
      var wasActive = canvas.getActiveObject() === grp;
      replaceCertImageGroup(grp, newG);
      if (wasActive) canvas.setActiveObject(newG);
      canvas.requestRenderAll();
      return;
    }

    var imgOpts = {};
    if (/^https?:\/\//i.test(url)) {
      imgOpts.crossOrigin = "anonymous";
    }

    fabric.Image.fromURL(
      url,
      function (fimg, isError) {
        if (_certDzImageHydrateTok[lid] !== myTok) return;
        if (isError || !fimg) return;
        var cur = canvas.getObjects().filter(function (o) {
          return o.layerId === lid && o.certLayerType === "image" && o.type === "group";
        })[0];
        if (!cur) return;

        var L = captureImageGroupLayout(cur);
        var gw = L.gw;
        var gh = L.gh;
        var iw0 = fimg.width || 1;
        var ih0 = fimg.height || 1;
        fimg.set({
          originX: "left",
          originY: "top",
          left: 0,
          top: 0,
          scaleX: gw / iw0,
          scaleY: gh / ih0,
        });
        var trimmed = (L.imageUrl || "").trim();
        var newG = buildCertImageGroup([fimg], {
          left: L.left,
          top: L.top,
          originX: L.originX,
          originY: L.originY,
          angle: L.angle,
          scaleX: 1,
          scaleY: 1,
          layerId: L.layerId,
          imageRole: L.imageRole,
          imageUrl: L.imageUrl,
          _certDzLoadedUrl: trimmed,
        });
        var wasActive = canvas.getActiveObject() === cur;
        replaceCertImageGroup(cur, newG);
        if (wasActive) canvas.setActiveObject(newG);
        canvas.requestRenderAll();
      },
      imgOpts
    );
  }

  function addQrLayer() {
    var qid = uid();
    var size = 70;
    var r = new fabric.Rect({
      left: PDF_W - 120,
      top: fabricTopFromPdfY(88, size),
      width: size,
      height: size,
      fill: "#f8fafc",
      stroke: "#334155",
      strokeWidth: 1,
      originX: "left",
      originY: "top",
    });
    r.layerId = qid;
    r.certLayerType = "qr";
    r.showCaption = true;
    var tx = new fabric.Text("QR", {
        fontSize: 14,
        fill: "#64748b",
        originX: "center",
        originY: "center",
        left: r.left + size / 2,
        top: r.top + size / 2,
      });
    var g = new fabric.Group([r, tx], { left: r.left, top: r.top, originX: "left", originY: "top" });
    g.layerId = qid;
    g.certLayerType = "qr";
    g.showCaption = true;
    canvas.add(g);
    canvas.setActiveObject(g);
    canvas.requestRenderAll();
    pushHistory();
  }

  function addLineLayer() {
    var lid = uid();
    var w = 200;
    var h = 2;
    var yPdf = 400;
    var x = 200;
    var rect = new fabric.Rect({
      left: x,
      top: fabricTopFromPdfY(yPdf, h),
      width: w,
      height: h,
      fill: "#0a1628",
      stroke: null,
      originX: "left",
      originY: "top",
    });
    rect.layerId = lid;
    rect.certLayerType = "line";
    canvas.add(rect);
    canvas.setActiveObject(rect);
    canvas.requestRenderAll();
    pushHistory();
  }

  function addRectLayer() {
    var rid = uid();
    var rect = new fabric.Rect({
      left: 300,
      top: fabricTopFromPdfY(350, 80),
      width: 200,
      height: 80,
      fill: "rgba(14,116,144,0.08)",
      stroke: "#0e7490",
      strokeWidth: 1,
      originX: "left",
      originY: "top",
    });
    rect.layerId = rid;
    rect.certLayerType = "rect";
    canvas.add(rect);
    canvas.setActiveObject(rect);
    canvas.requestRenderAll();
    pushHistory();
  }

  function loadLayer(L) {
    var z = L.zIndex || 0;
    var t = (L.type || "text").toLowerCase();
    if (t === "text") {
      var h = L.heightPt || 40;
      var top = fabricTopFromPdfY(L.yPt, h);
      var vKey = String(L.variable || "static").toLowerCase();
      var stored = (L.text != null && L.text !== "") ? String(L.text) : "";
      var displayText = stored;
      if (!displayText) {
        displayText = vKey === "static" ? "Text" : previewSampleForVariable(vKey);
      }
      var tb = new fabric.Textbox(displayText, {
        left: L.xPt,
        top: top,
        width: L.widthPt || 400,
        fontSize: L.fontSize || L.size || 16,
        fontFamily: fontKeyToFabricFamily(L.font),
        fill: L.color || "#0a1628",
        fontWeight: L.bold ? "bold" : "normal",
        fontStyle: L.italic ? "italic" : "normal",
        textAlign: L.align || "left",
        underline: !!L.underline,
        originX: "left",
        originY: "top",
        opacity: vKey === "static" ? 1 : 0.92,
      });
      if ((L.rotation || 0) !== 0) tb.set({ angle: L.rotation });
      tb.layerId = L.id || uid();
      tb.certLayerType = "text";
      tb.variable = (L.variable || "static").toLowerCase();
      canvas.add(tb);
      return;
    }
    if (t === "image") {
      var ih = L.heightPt || 60;
      var itop = fabricTopFromPdfY(L.yPt, ih);
      var rect = new fabric.Rect({
        left: L.xPt,
        top: itop,
        width: L.widthPt || 80,
        height: ih,
        fill: "#f1f5f9",
        stroke: "#94a3b8",
        strokeWidth: 1,
        originX: "left",
        originY: "top",
      });
      rect.layerId = L.id || uid();
      rect.certLayerType = "image";
      rect.imageRole = (L.imageRole || "custom").toLowerCase();
      rect.imageUrl = L.url || "";
      var glabel =
        rect.imageRole === "logo" ? "Logo" : rect.imageRole === "signature" ? "Signature" : "Image";
      var lt = new fabric.Text(glabel, {
        fontSize: 11,
        fill: "#64748b",
        originX: "center",
        originY: "center",
        left: rect.left + rect.width / 2,
        top: rect.top + rect.height / 2,
      });
      var grp = new fabric.Group([rect, lt], {
        left: L.xPt,
        top: itop,
        originX: "left",
        originY: "top",
      });
      grp.layerId = L.id || uid();
      grp.certLayerType = "image";
      grp.imageRole = rect.imageRole;
      grp.imageUrl = rect.imageUrl;
      if ((L.rotation || 0) !== 0) grp.set({ angle: L.rotation });
      canvas.add(grp);
      if ((grp.imageUrl || "").trim()) {
        hydrateCertImageLayer(grp);
      }
      return;
    }
    if (t === "qr") {
      var qs = L.widthPt || 70;
      var qh = L.heightPt || qs;
      var qtop = fabricTopFromPdfY(L.yPt, qh);
      var r = new fabric.Rect({
        left: L.xPt,
        top: qtop,
        width: qs,
        height: qh,
        fill: "#f8fafc",
        stroke: "#334155",
        strokeWidth: 1,
        originX: "left",
        originY: "top",
      });
      var tx = new fabric.Text("QR", {
        fontSize: 14,
        fill: "#64748b",
        originX: "center",
        originY: "center",
        left: r.left + qs / 2,
        top: r.top + qh / 2,
      });
      var g = new fabric.Group([r, tx], { left: L.xPt, top: qtop, originX: "left", originY: "top" });
      g.layerId = L.id || uid();
      g.certLayerType = "qr";
      g.showCaption = L.showCaption !== false;
      if ((L.rotation || 0) !== 0) g.set({ angle: L.rotation });
      canvas.add(g);
      return;
    }
    if (t === "line") {
      var lw = (L.x2Pt != null ? L.x2Pt - L.xPt : L.widthPt) || 200;
      var lh = 2;
      var ltop = fabricTopFromPdfY(L.yPt, lh);
      var rect = new fabric.Rect({
        left: L.xPt,
        top: ltop,
        width: lw,
        height: lh,
        fill: L.color || "#0a1628",
        originX: "left",
        originY: "top",
      });
      rect.layerId = L.id || uid();
      rect.certLayerType = "line";
      rect.strokeWidth = L.lineWidth || 1.5;
      if ((L.rotation || 0) !== 0) rect.set({ angle: L.rotation });
      canvas.add(rect);
      return;
    }
    if (t === "rect") {
      var rh = L.heightPt || 40;
      var rtop = fabricTopFromPdfY(L.yPt, rh);
      var rect = new fabric.Rect({
        left: L.xPt,
        top: rtop,
        width: L.widthPt || 100,
        height: rh,
        fill: L.fillColor || "transparent",
        stroke: L.strokeColor || "#64748b",
        strokeWidth: L.strokeWidth != null ? L.strokeWidth : 1,
        originX: "left",
        originY: "top",
      });
      if (!L.fillColor) rect.set({ fill: "transparent" });
      rect.layerId = L.id || uid();
      rect.certLayerType = "rect";
      if ((L.rotation || 0) !== 0) rect.set({ angle: L.rotation });
      canvas.add(rect);
    }
  }

  function loadDocument(d) {
    canvas.clear();
    canvas.backgroundColor = "#ffffff";
    doc = JSON.parse(JSON.stringify(d));
    syncPageFields();
    var layers = (d.layers || []).slice().sort(function (a, b) {
      return (a.zIndex || 0) - (b.zIndex || 0);
    });
    layers.forEach(loadLayer);
    drawPageChrome();
    drawPageBackground();
    canvas.requestRenderAll();
  }

  function syncPageFields() {
    document.getElementById("cert-dz-border-style").value = doc.border_style || "classic";
    document.getElementById("cert-dz-border-width").value = doc.border_width != null ? doc.border_width : 1;
    document.getElementById("cert-dz-bg-size").value = doc.bg_size || "cover";
    var pbg = document.getElementById("cert-dz-page-bg-url");
    if (pbg) pbg.value = doc.background_image_url != null ? doc.background_image_url : "";
  }

  function fillToHex(fill) {
    if (typeof fill === "string" && fill.charAt(0) === "#" && fill.length >= 7) return fill.slice(0, 7).toLowerCase();
    return "#0a1628";
  }

  function setColorAndHex(hexVal) {
    var cEl = document.getElementById("cert-dz-prop-color");
    var hEl = document.getElementById("cert-dz-prop-color-hex");
    var h = fillToHex(hexVal);
    if (cEl) cEl.value = h;
    if (hEl) hEl.value = h;
  }

  var varSelect = document.getElementById("cert-dz-prop-variable");
  VARIABLE_OPTS.forEach(function (o) {
    var opt = document.createElement("option");
    opt.value = o.v;
    opt.textContent = o.l;
    varSelect.appendChild(opt);
  });

  function getTargetObject() {
    var o = canvas.getActiveObject();
    if (!o) return null;
    if (o.type === "activeSelection" && o._objects && o._objects.length === 1) {
      return o._objects[0];
    }
    return o;
  }

  function updatePropsPanel() {
    var o = getTargetObject();
    var none = document.getElementById("cert-dz-sel-none");
    var panel = document.getElementById("cert-dz-sel-panel");
    if (!o || !o.certLayerType) {
      none.style.display = "block";
      panel.style.display = "none";
      return;
    }
    none.style.display = "none";
    panel.style.display = "block";
    var t = o.certLayerType;

    /* Geometry first: cert-dz-prop-align dispatches "change" below, which runs applyPropsFromForm and
       must see this selection's w/h — not the previous object's (stale values caused scaleX squash). */
    var geomW = o.getScaledWidth();
    var geomH = o.getScaledHeight();
    document.getElementById("cert-dz-prop-w").value = Math.round(geomW);
    document.getElementById("cert-dz-prop-h").value = Math.round(geomH);
    document.getElementById("cert-dz-prop-rot").value = Math.round(o.angle || 0);

    document.getElementById("cert-dz-prop-variable").disabled = t !== "text";
    document.getElementById("cert-dz-prop-text").disabled = t !== "text";
    document.getElementById("cert-dz-prop-font").disabled = t !== "text";
    document.getElementById("cert-dz-prop-fontsize").disabled = t !== "text";
    document.getElementById("cert-dz-prop-color").disabled = t !== "text" && t !== "rect" && t !== "line";
    var hHexEl = document.getElementById("cert-dz-prop-color-hex");
    if (hHexEl) hHexEl.disabled = t !== "text" && t !== "rect" && t !== "line";
    document.getElementById("cert-dz-prop-bold").disabled = t !== "text";
    document.getElementById("cert-dz-prop-italic").disabled = t !== "text";
    document.getElementById("cert-dz-prop-underline").disabled = t !== "text";
    document.getElementById("cert-dz-prop-imgurl").disabled = t !== "image";
    document.getElementById("cert-dz-prop-qrcaption").disabled = t !== "qr";

    if (t === "text" && (o.type === "textbox" || o.type === "i-text" || o.type === "text")) {
      varSelect.value = (o.variable || "static").toLowerCase();
      document.getElementById("cert-dz-prop-text").value = o.text || "";
      document.getElementById("cert-dz-prop-font").value =
        (o.fontFamily || "Arial").toLowerCase().indexOf("georg") >= 0
          ? "georgia"
          : (o.fontFamily || "arial").toLowerCase().indexOf("times") >= 0
            ? "times"
            : "arial";
      document.getElementById("cert-dz-prop-fontsize").value = o.fontSize || 16;
      setColorAndHex(o.fill);
      document.getElementById("cert-dz-prop-bold").checked = o.fontWeight === "bold";
      document.getElementById("cert-dz-prop-italic").checked = o.fontStyle === "italic";
      document.getElementById("cert-dz-prop-underline").checked = !!o.underline;
      var al = document.getElementById("cert-dz-prop-align");
      if (al) {
        al.value = o.textAlign || "left";
        al.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
    if (t === "image") {
      document.getElementById("cert-dz-prop-imgurl").value = o.imageUrl || "";
    }
    if (t === "qr") {
      document.getElementById("cert-dz-prop-qrcaption").checked = o.showCaption !== false;
    }
    if (t === "rect" || t === "line") {
      var fillOrStroke = t === "line" ? o.fill || o.stroke : o.fill;
      if (fillOrStroke) setColorAndHex(fillOrStroke);
    }

    if (typeof window._certDzApplyTypeVis === "function") window._certDzApplyTypeVis(t);
  }

  function applyPropsFromForm() {
    var o = getTargetObject();
    if (!o || !o.certLayerType) return;
    var t = o.certLayerType;
    if (t === "text" && (o.type === "textbox" || o.type === "i-text" || o.type === "text")) {
      o.set({
        variable: varSelect.value,
        text: document.getElementById("cert-dz-prop-text").value,
        fontFamily: fontKeyToFabricFamily(document.getElementById("cert-dz-prop-font").value),
        fontSize: parseFloat(document.getElementById("cert-dz-prop-fontsize").value) || 16,
        fill: document.getElementById("cert-dz-prop-color").value,
        fontWeight: document.getElementById("cert-dz-prop-bold").checked ? "bold" : "normal",
        fontStyle: document.getElementById("cert-dz-prop-italic").checked ? "italic" : "normal",
        underline: document.getElementById("cert-dz-prop-underline").checked,
        textAlign: document.getElementById("cert-dz-prop-align").value,
      });
    }
    if (t === "image") {
      o.set({ imageUrl: document.getElementById("cert-dz-prop-imgurl").value });
    }
    if (t === "qr") {
      o.set({ showCaption: document.getElementById("cert-dz-prop-qrcaption").checked });
    }
    if (t === "rect" || t === "line") {
      var cFill = document.getElementById("cert-dz-prop-color");
      if (cFill) o.set({ fill: cFill.value });
    }
    var nw = parseFloat(document.getElementById("cert-dz-prop-w").value);
    var nh = parseFloat(document.getElementById("cert-dz-prop-h").value);
    if (nw > 0 && nh > 0) {
      var cw = o.getScaledWidth();
      var ch = o.getScaledHeight();
      if (cw > 0 && ch > 0) {
        if (t === "text" && (o.type === "textbox" || o.type === "i-text")) {
          var sx = Math.abs(o.scaleX) || 1;
          o.set({
            width: Math.max(20, nw / sx),
            scaleX: 1,
            scaleY: (o.scaleY || 1) * (nh / ch),
          });
        } else {
          o.set({
            scaleX: (o.scaleX || 1) * (nw / cw),
            scaleY: (o.scaleY || 1) * (nh / ch),
          });
        }
      }
    }
    var rot = parseFloat(document.getElementById("cert-dz-prop-rot").value);
    if (!isNaN(rot)) o.set({ angle: rot });
    o.setCoords();
    if (t === "image") {
      var tg = getTargetObject();
      if (tg && tg.certLayerType === "image") {
        var wanted = (tg.imageUrl || "").trim();
        if (!wanted) {
          hydrateCertImageLayer(tg);
        } else if ((tg._certDzLoadedUrl || "") === wanted && scaleInnerImageToGroupBounds(tg)) {
          /* resized in place */
        } else {
          hydrateCertImageLayer(tg);
        }
      }
    }
    canvas.requestRenderAll();
  }

  [
    "cert-dz-prop-variable",
    "cert-dz-prop-text",
    "cert-dz-prop-font",
    "cert-dz-prop-fontsize",
    "cert-dz-prop-color",
    "cert-dz-prop-color-hex",
    "cert-dz-prop-bold",
    "cert-dz-prop-italic",
    "cert-dz-prop-underline",
    "cert-dz-prop-align",
    "cert-dz-prop-imgurl",
    "cert-dz-prop-qrcaption",
    "cert-dz-prop-w",
    "cert-dz-prop-h",
    "cert-dz-prop-rot",
  ].forEach(function (id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("change", function () {
      applyPropsFromForm();
      pushHistory();
    });
    el.addEventListener("input", function () {
      if (
        id.indexOf("rot") >= 0 ||
        id.indexOf("prop-w") >= 0 ||
        id.indexOf("prop-h") >= 0 ||
        id === "cert-dz-prop-color" ||
        id === "cert-dz-prop-color-hex"
      ) {
        applyPropsFromForm();
      }
    });
  });

  canvas.on("selection:created", updatePropsPanel);
  canvas.on("selection:updated", updatePropsPanel);
  canvas.on("selection:cleared", updatePropsPanel);
  canvas.on("object:modified", function () {
    pushHistory();
    updatePropsPanel();
  });

  var certDzToolbar = document.getElementById("cert-dz-toolbar");
  if (certDzToolbar) {
  certDzToolbar.addEventListener("click", function (e) {
    var vItem = e.target.closest(".cert-dz-varfield-item");
    if (vItem) {
      e.preventDefault();
      e.stopPropagation();
      var vk = vItem.getAttribute("data-varkey") || "attendee_name";
      addTextLayer(vk, "");
      var menu = document.getElementById("cert-dz-varfield-menu");
      var trigger = document.getElementById("cert-dz-varfield-trigger");
      if (menu) menu.hidden = true;
      if (trigger) trigger.setAttribute("aria-expanded", "false");
      return;
    }
    var btn = e.target.closest("[data-add]");
    if (!btn) return;
    var k = btn.getAttribute("data-add");
    if (k === "text") addTextLayer("static", "Your text");
    else if (k === "image-logo") addImagePlaceholder("logo", "");
    else if (k === "image-sig") addImagePlaceholder("signature", "");
    else if (k === "image-url") {
      var u = window.prompt("Image URL (https or site path)", "https://");
      if (u) addImagePlaceholder("custom", u);
    } else if (k === "qr") addQrLayer();
    else if (k === "line") addLineLayer();
    else if (k === "rect") addRectLayer();
  });
  } else {
    console.error("certificate-designer: #cert-dz-toolbar missing");
  }

  document.getElementById("cert-dz-delete").addEventListener("click", function () {
    var o = getTargetObject();
    if (o) {
      canvas.remove(o);
      canvas.discardActiveObject();
      canvas.requestRenderAll();
      pushHistory();
    }
  });

  document.getElementById("cert-dz-duplicate").addEventListener("click", function () {
    var o = getTargetObject();
    if (!o) return;
    o.clone(function (cloned) {
      cloned.set({ left: (cloned.left || 0) + 20, top: (cloned.top || 0) + 20 });
      cloned.layerId = uid();
      cloned.certLayerType = o.certLayerType;
      cloned.variable = o.variable;
      cloned.imageRole = o.imageRole;
      cloned.imageUrl = o.imageUrl;
      if (o.certLayerType === "image") cloned._certDzLoadedUrl = o._certDzLoadedUrl;
      cloned.showCaption = o.showCaption;
      canvas.add(cloned);
      canvas.setActiveObject(cloned);
      canvas.requestRenderAll();
      pushHistory();
    });
  });

  document.getElementById("cert-dz-front").addEventListener("click", function () {
    var o = getTargetObject();
    if (o) {
      canvas.bringToFront(o);
      canvas.requestRenderAll();
      pushHistory();
    }
  });

  document.getElementById("cert-dz-back").addEventListener("click", function () {
    var o = getTargetObject();
    if (o) {
      canvas.sendToBack(o);
      canvas.requestRenderAll();
      pushHistory();
    }
  });

  document.getElementById("cert-dz-undo").addEventListener("click", function () {
    if (histPtr > 0) applyHistory(histPtr - 1);
  });
  document.getElementById("cert-dz-redo").addEventListener("click", function () {
    if (histPtr < history.length - 1) applyHistory(histPtr + 1);
  });

  document.getElementById("cert-dz-convert").addEventListener("click", function () {
    if (!window.confirm("Replace the current canvas with layers converted from the saved legacy template?")) return;
    fetch(designerLegacyUrl, { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (data.error) throw new Error(data.error);
        loadDocument(data);
        syncPageFields();
        pushHistory();
      })
      .catch(function (err) {
        window.alert("Could not convert: " + (err.message || err));
      });
  });

  document.getElementById("cert-dz-reset").addEventListener("click", function () {
    if (!window.confirm("Reload the page to restore the last saved layout from the server?")) return;
    location.reload();
  });

  function certDzParseJsonSafe(text) {
    try {
      return JSON.parse(text);
    } catch (ignore) {
      return null;
    }
  }

  function certDzErrorMessageFromBody(text, status) {
    var j = certDzParseJsonSafe(text);
    if (j && j.detail != null) {
      if (typeof j.detail === "string") return j.detail;
      return JSON.stringify(j.detail);
    }
    if (j && j.error) return String(j.error);
    if (text && text.indexOf("<!DOCTYPE") !== -1) {
      return "Server returned a login or error page (HTTP " + status + "). Try signing in again.";
    }
    return text ? String(text).slice(0, 240) : "Save failed (HTTP " + status + ")";
  }

  function certDzToast(msg, kind) {
    try {
      if (window.TechTrek && typeof TechTrek.showToast === "function") {
        TechTrek.showToast(msg, kind || "info");
      } else {
        window.alert(msg);
      }
    } catch (e) {
      window.alert(msg);
    }
  }

  var aiGenBtn = document.getElementById("cert-dz-ai-generate");
  if (aiGenBtn) {
    aiGenBtn.addEventListener("click", function () {
      if (
        !window.confirm(
          "Generate a new background with AI and replace the canvas? This runs two OpenAI API calls (billable latency ~30–90s)."
        )
      ) {
        return;
      }
      var hint = window.prompt("Optional style hint (leave blank for default):", "") || "";
      hint = String(hint).slice(0, 2000);
      var btn = aiGenBtn;
      var prevLabel = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Generating artwork…";
      var phaseTimer = window.setTimeout(function () {
        if (!btn.disabled) return;
        btn.textContent = "Placing text fields…";
      }, 4500);
      fetch(aiGenerateUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ prompt_hint: hint }),
      })
        .then(function (r) {
          return r.text().then(function (text) {
            if (!r.ok) throw new Error(certDzErrorMessageFromBody(text, r.status));
            var data = certDzParseJsonSafe(text);
            if (!data || typeof data.cert_style !== "object") {
              throw new Error("Invalid response from server.");
            }
            return data;
          });
        })
        .then(function (data) {
          loadDocument(data.cert_style);
          syncPageFields();
          pushHistory();
          if (data.layout_fallback) {
            certDzToast(
              "Vision step used default text/QR positions. Adjust layers in the designer if needed.",
              "warning"
            );
          } else {
            certDzToast("AI template loaded. Review the layout, then save.", "success");
          }
        })
        .catch(function (err) {
          window.alert(err.message || err);
        })
        .finally(function () {
          window.clearTimeout(phaseTimer);
          btn.disabled = false;
          btn.textContent = prevLabel;
        });
    });
  }

  var saveBtn = document.getElementById("cert-dz-save");
  if (saveBtn) {
    saveBtn.addEventListener("click", function () {
      var btn = saveBtn;
      var payload;
      try {
        payload = serializeDocument();
      } catch (err) {
        console.error(err);
        window.alert("Could not build layout: " + (err.message || String(err)));
        return;
      }
      var body;
      try {
        body = JSON.stringify({ cert_style: payload });
      } catch (err) {
        console.error(err);
        window.alert("Could not serialize layout. Try removing a problematic layer or reload the page.");
        return;
      }
      btn.disabled = true;
      fetch(designerSaveUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        credentials: "same-origin",
        body: body,
      })
        .then(function (r) {
          return r.text().then(function (text) {
            if (!r.ok) {
              throw new Error(certDzErrorMessageFromBody(text, r.status));
            }
            var data = certDzParseJsonSafe(text);
            if (data == null && (!text || !text.trim())) {
              return { ok: true };
            }
            if (data == null) {
              throw new Error(
                "Save succeeded but response was not JSON. Check that you are still logged in as admin."
              );
            }
            return data;
          });
        })
        .then(function () {
          doc = payload;
          try {
            if (window.TechTrek && typeof TechTrek.showToast === "function") {
              TechTrek.showToast("Layout saved.", "success");
            } else {
              window.alert("Saved.");
            }
          } catch (toastErr) {
            window.alert("Saved.");
          }
        })
        .catch(function (e) {
          window.alert(e.message || "Save failed");
        })
        .finally(function () {
          btn.disabled = false;
        });
    });
  }

  canvas.on("object:moving", function (opt) {
    if (!document.getElementById("cert-dz-snap").checked) return;
    var o = opt.target;
    var g = grid;
    o.set({
      left: snap(o.left, g),
      top: snap(o.top, g),
    });
  });

  document.getElementById("cert-dz-zoom").addEventListener("input", function () {
    var z = Math.max(0.35, Math.min(2, parseFloat(this.value) || 0.75));
    canvas.setZoom(z);
    canvas.setDimensions({ width: PDF_W * z, height: PDF_H * z });
    if (typeof canvas.calcOffset === "function") canvas.calcOffset();
    canvas.requestRenderAll();
  });

  ["cert-dz-border-style", "cert-dz-border-width", "cert-dz-bg-size"].forEach(function (id) {
    var el = document.getElementById(id);
    if (!el) return;
    function onPageFieldInput() {
      syncDocPageFieldsFromForm();
      drawPageChrome();
      drawPageBackground();
    }
    el.addEventListener("change", onPageFieldInput);
    if (id === "cert-dz-border-width") el.addEventListener("input", onPageFieldInput);
  });

  var pageBgUrlEl = document.getElementById("cert-dz-page-bg-url");
  if (pageBgUrlEl) {
    function onPageBgField() {
      syncDocPageFieldsFromForm();
      drawPageBackground();
    }
    pageBgUrlEl.addEventListener("change", function () {
      onPageBgField();
      pushHistory();
    });
    pageBgUrlEl.addEventListener("input", onPageBgField);
  }

  var toolbarImgFile = document.getElementById("cert-dz-toolbar-img-file");
  var toolbarImgUploadBtn = document.getElementById("cert-dz-image-upload");
  if (toolbarImgUploadBtn && toolbarImgFile) {
    toolbarImgUploadBtn.addEventListener("click", function () {
      toolbarImgFile.click();
    });
    toolbarImgFile.addEventListener("change", function (ev) {
      var f = ev.target.files && ev.target.files[0];
      if (!f) return;
      uploadCertImage(f, function (relUrl) {
        addImagePlaceholder("custom", relUrl);
        pushHistory();
      });
      ev.target.value = "";
    });
  }

  var canvasShell = document.querySelector(".cert-dz-canvas-shell");
  if (canvasShell) {
    canvasShell.addEventListener(
      "wheel",
      function (e) {
        if (!e.ctrlKey && !e.metaKey) return;
        e.preventDefault();
        var zEl = document.getElementById("cert-dz-zoom");
        if (!zEl) return;
        var z = parseFloat(zEl.value) || 0.75;
        var step = e.deltaY > 0 ? -0.06 : 0.06;
        z = Math.max(0.35, Math.min(2, Math.round((z + step) * 100) / 100));
        zEl.value = String(z);
        zEl.dispatchEvent(new Event("input"));
      },
      { passive: false }
    );
  }

  loadDocument(doc);
  pushHistory();

  var zEl = document.getElementById("cert-dz-zoom");
  if (zEl) zEl.dispatchEvent(new Event("input"));
  if (typeof canvas.calcOffset === "function") canvas.calcOffset();
  canvas.requestRenderAll();

  document.addEventListener("keydown", function (e) {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT")
      return;
    var o = getTargetObject();
    if (!o) return;
    var step = e.shiftKey ? 10 : 1;
    if (e.key === "ArrowLeft") {
      o.set({ left: o.left - step });
      e.preventDefault();
    } else if (e.key === "ArrowRight") {
      o.set({ left: o.left + step });
      e.preventDefault();
    } else if (e.key === "ArrowUp") {
      o.set({ top: o.top - step });
      e.preventDefault();
    } else if (e.key === "ArrowDown") {
      o.set({ top: o.top + step });
      e.preventDefault();
    } else return;
    o.setCoords();
    canvas.requestRenderAll();
    pushHistory();
  });
})();
