/* Mr Roy. 16 x 22 pixels on a canvas, nearest-neighbour scaled.

   An old-school Indian professor of English: silver hair swept back, a
   full silver moustache, spectacles, and a dark jacket over a high-collared
   kurta. Courteous, exacting, entirely without condescension.

   s skin   d shadow   h hair/brows   m mouth   g spectacles
   k kurta (high collar)   j jacket   t pocket square   p trousers  o shoes */

(function () {
  var PALETTE = {
    s: "#8A5433", d: "#6B3F26", h: "#D8D4CC", m: "#3B2419", g: "#2A2E33",
    k: "#F2EFE8", j: "#1E2A38", t: "#B5852A", p: "#232C36", o: "#14181D"
  };

  var BODY = [
    "................",
    "....hhhhhhhh....",   // swept-back silver hair
    "...hhhhhhhhhh...",
    "...hsssssssshd..",
    "...hsssssssssd..",
    "...ggggggggggd..",   // spectacles across the whole face
    "....ssssssssd...",
    "....shhhhhhsd...",   // full moustache
    "....ss....ssd...",   // mouth row, filled per frame
    ".....ssssssd....",
    "......ssss......",   // neck
    ".....kkkkkk.....",   // high kurta collar
    "...jjkkkkkkjj...",
    "..jjjkkkkkkjjj..",
    "..jjtkkkkkkjjj..",   // pocket square
    "..sjjkkkkkkjjs..",   // hands at the cuffs
    "...jjjkkkkjjj...",
    "...pppppppppp...",
    "...ppp....ppp...",
    "...ppp....ppp...",
    "...ppp....ppp...",
    "..oooo....oooo.."
  ];

  var EYES_OPEN = "...gmggmggmggd..";   // dark pupils behind the lenses
  var EYES_SHUT = "...gggggggggggd.";
  var BROW_UP   = "...hhhhhhhhhhd..";   // a raised eyebrow, used sparingly
  var BROW_REST = "...hsssssssshd..";
  var MOUTH_SHUT = "....ssssssssd...";
  var MOUTH_OPEN = "....ssmmmmssd...";
  var MOUTH_WIDE = "....smmmmmmsd...";

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

    // breathing: the head and torso lift one pixel every other beat
    var bob = this.reduced ? 0 : (Math.floor(frame / 4) % 2);
    var blinking = !this.reduced && frame % 25 === 0;
    // a considered eyebrow, only while making a point
    var brow = this.talking && Math.floor(frame / 6) % 3 === 0;

    var mouth = MOUTH_SHUT;
    if (this.talking) mouth = frame % 2 ? MOUTH_OPEN : MOUTH_WIDE;

    for (var y = 0; y < BODY.length; y++) {
      var row = BODY[y];
      if (y === 3) row = brow ? BROW_UP : BROW_REST;
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
