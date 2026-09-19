/* Mr Tharoor. 16 x 22 pixels on a canvas, nearest-neighbour scaled.

   The archetype of the Indian statesman-scholar: silver-streaked hair swept
   back, spectacles hanging on a cord at the chest, a dark blue Nehru
   waistcoat over a pale collared shirt, pocket square, and a warm, faintly
   amused expression. Courteous, exacting, never condescending.

   s skin   d shadow   h hair   b brow   e eye   m mouth
   c shirt (pale)   v waistcoat (indigo)   g spectacles on their cord
   t pocket square  p trousers  o shoes */

(function () {
  var PALETTE = {
    s: "#9C6239", d: "#7A4A2A", h: "#4A4440", b: "#B8B2AC", e: "#241A14",
    m: "#6B3C33", c: "#E8EDF2", v: "#2C3E5C", g: "#1A1D22", t: "#C9A227",
    p: "#242A33", o: "#15181D"
  };

  var BODY = [
    "................",
    "....hhhhhhhh....",   // hair swept back, silver at the temples
    "...hbhhhhhhbhd..",
    "...hssssssssshd.",
    "...hssssssssshd.",
    "....s.ss.ss.sd..",   // eyes, filled per frame
    "....ssssssssd...",
    "....sdssssdsd...",   // the faint smile lines
    "....ss....ssd...",   // mouth row, filled per frame
    ".....ssssssd....",
    "......ssss......",   // neck
    "....ccgccgcc....",   // shirt collar, spectacle cord over it
    "...cvvgccgvvc...",   // waistcoat opens over the shirt
    "..cvvvggggvvvc..",   // the spectacles themselves, resting at the chest
    "..cvvvvccvvvvc..",
    "..svvvtccvvvvs..",   // pocket square, hands at the cuffs
    "...vvvvccvvvv...",
    "...pppppppppp...",
    "...ppp....ppp...",
    "...ppp....ppp...",
    "...ppp....ppp...",
    "..oooo....oooo.."
  ];

  var EYES_OPEN = "....seesseesd...";
  var EYES_SHUT = "....sddssddsd...";
  var BROW_UP   = "...bhbhhhhhbhd..";   // one eyebrow raised, used when talking
  var BROW_REST = "...hbhhhhhhbhd..";
  var MOUTH_SHUT = "....smmmmmmsd...";  // a settled, faint smile at rest
  var MOUTH_OPEN = "....smmmmmmsd...";
  var MOUTH_WIDE = "....mmmmmmmmd...";

  function Roy(canvas, scale) {
    this.ctx = canvas.getContext("2d");
    this.scale = scale || 6;
    canvas.width = 16 * this.scale;
    canvas.height = 22 * this.scale;
    canvas.style.width = canvas.width + "px";
    canvas.style.height = canvas.height + "px";
    this.ctx.imageSmoothingEnabled = false;
    this.talking = false;
    this.frame = 0;
    this.reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.tick = this.tick.bind(this);
    this.draw(0);
    if (!this.reduced) this.timer = setInterval(this.tick, 160);
  }

  Roy.prototype.tick = function () {
    this.frame++;
    this.draw(this.frame);
  };

  Roy.prototype.draw = function (frame) {
    var ctx = this.ctx, s = this.scale;
    ctx.clearRect(0, 0, 16 * s, 22 * s);

    var bob = this.reduced ? 0 : (Math.floor(frame / 4) % 2);
    var blinking = !this.reduced && frame % 25 === 0;
    // the eyebrow goes up only while he is making a point
    var brow = this.talking && Math.floor(frame / 6) % 3 === 0;

    var mouth = MOUTH_SHUT;
    if (this.talking) mouth = frame % 2 ? MOUTH_OPEN : MOUTH_WIDE;

    for (var y = 0; y < BODY.length; y++) {
      var row = BODY[y];
      if (y === 2) row = brow ? BROW_UP : BROW_REST;
      if (y === 5) row = blinking ? EYES_SHUT : EYES_OPEN;
      if (y === 8) row = mouth;
      var offset = y < 17 ? bob : 0;   // feet stay planted
      for (var x = 0; x < row.length; x++) {
        var colour = PALETTE[row[x]];
        if (!colour) continue;
        ctx.fillStyle = colour;
        ctx.fillRect(x * s, (y + offset) * s, s, s);
      }
    }
  };

  Roy.prototype.say = function (on) {
    this.talking = !!on;
    this.draw(this.frame);
  };

  window.Roy = Roy;
})();
