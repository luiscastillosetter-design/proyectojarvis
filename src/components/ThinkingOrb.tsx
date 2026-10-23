"use client";
import React, { useEffect, useRef } from "react";

interface ThinkingOrbProps {
  status?: "idle" | "listening" | "thinking" | "speaking";
  onClick?: () => void;
  size?: "hero" | "normal";
}

export default function ThinkingOrb({
  status = "idle",
  onClick,
  size = "hero",
}: ThinkingOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animationId: number;
    let t = 0;

    // 70 partículas de plasma orbitales de alta densidad
    const particles = Array.from({ length: 70 }, (_, i) => ({
      angle: (i / 70) * Math.PI * 2,
      radiusOffset: (Math.random() - 0.5) * 26,
      speed: (0.007 + Math.random() * 0.018) * (i % 2 === 0 ? 1 : -1),
      size: 1.2 + Math.random() * 2.6,
      alpha: 0.45 + Math.random() * 0.55,
    }));

    const render = () => {
      const speedMult =
        status === "thinking" ? 2.6 : status === "speaking" ? 2.0 : status === "listening" ? 1.6 : 0.85;
      t += 0.024 * speedMult;

      const w = canvas.width;
      const h = canvas.height;
      const cx = w / 2;
      const cy = h / 2;

      ctx.clearRect(0, 0, w, h);
      ctx.save();
      ctx.globalCompositeOperation = "lighter";

      let primaryRGB = "0, 229, 255"; // Cyan Stark
      let secondaryRGB = "0, 110, 255"; // Azul Cobalto
      let accentRGB = "168, 85, 247"; // Violeta Cuántico

      if (status === "listening") {
        primaryRGB = "0, 255, 190";
        secondaryRGB = "0, 215, 255";
        accentRGB = "16, 185, 129";
      } else if (status === "thinking") {
        primaryRGB = "192, 108, 255";
        secondaryRGB = "0, 229, 255";
        accentRGB = "244, 63, 94";
      } else if (status === "speaking") {
        primaryRGB = "0, 245, 255";
        secondaryRGB = "59, 130, 246";
        accentRGB = "139, 92, 246";
      }

      // 1. Resplandor volumétrico exterior profundo
      const outerGlow = ctx.createRadialGradient(cx, cy, 18, cx, cy, 172);
      outerGlow.addColorStop(0, `rgba(${primaryRGB}, 0.30)`);
      outerGlow.addColorStop(0.5, `rgba(${secondaryRGB}, 0.16)`);
      outerGlow.addColorStop(1, "rgba(0, 0, 0, 0)");
      ctx.fillStyle = outerGlow;
      ctx.beginPath();
      ctx.arc(cx, cy, 172, 0, Math.PI * 2);
      ctx.fill();

      // 2. Anillo Mecánico Exterior FUI (Segmentos + Aletas de Calibre Iron Man)
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(t * 0.22);
      const outerArcs = [
        [0, 1.05],
        [1.35, 2.65],
        [3.0, 4.25],
        [4.6, 5.95],
      ];
      ctx.strokeStyle = `rgba(${primaryRGB}, 0.85)`;
      ctx.lineWidth = 3;
      outerArcs.forEach(([start, end]) => {
        ctx.beginPath();
        ctx.arc(0, 0, 152, start, end);
        ctx.stroke();
      });

      for (let i = 0; i < 4; i++) {
        const ang = (i * Math.PI) / 2 + 0.35;
        ctx.beginPath();
        ctx.moveTo(Math.cos(ang) * 144, Math.sin(ang) * 144);
        ctx.lineTo(Math.cos(ang) * 162, Math.sin(ang) * 162);
        ctx.arc(0, 0, 162, ang, ang + 0.42);
        ctx.strokeStyle = `rgba(${primaryRGB}, 0.65)`;
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      ctx.restore();

      // 3. Corona de 120 Grados de Telemetría
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(-t * 0.16);
      const numTicks = 120;
      for (let i = 0; i < numTicks; i++) {
        const ang = (i / numTicks) * Math.PI * 2;
        const isMajor = i % 10 === 0;
        const rInner = isMajor ? 124 : 130;
        const rOuter = isMajor ? 138 : 135;
        ctx.beginPath();
        ctx.moveTo(Math.cos(ang) * rInner, Math.sin(ang) * rInner);
        ctx.lineTo(Math.cos(ang) * rOuter, Math.sin(ang) * rOuter);
        ctx.strokeStyle = isMajor ? `rgba(${primaryRGB}, 0.95)` : `rgba(${secondaryRGB}, 0.45)`;
        ctx.lineWidth = isMajor ? 2.2 : 1;
        ctx.stroke();
      }
      ctx.restore();

      // 4. Triple Anillo de Plasma Orgánico (Estilo descarga (22).jpg)
      const plasmaRadius = 108 + Math.sin(t * 2.2) * 3.5;
      for (let wv = 0; wv < 3; wv++) {
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(t * (wv % 2 === 0 ? 0.55 : -0.45) + wv * 1.1);
        ctx.beginPath();
        for (let a = 0; a <= Math.PI * 2; a += 0.06) {
          const distortion =
            Math.sin(a * 7 + t * 3.5) * (status === "idle" ? 3.5 : 8) +
            Math.cos(a * 5 - t * 2.2) * 2.8;
          const r = plasmaRadius + distortion;
          const x = Math.cos(a) * r;
          const y = Math.sin(a) * r;
          if (a === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.strokeStyle =
          wv === 0
            ? `rgba(${primaryRGB}, 0.95)`
            : wv === 1
            ? `rgba(${accentRGB}, 0.75)`
            : `rgba(${secondaryRGB}, 0.80)`;
        ctx.lineWidth = wv === 0 ? 4 : 2.2;
        ctx.shadowColor = `rgb(${primaryRGB})`;
        ctx.shadowBlur = 22;
        ctx.stroke();
        ctx.restore();
      }

      // 5. Ecualizador Radial de 80 Barras (Estilo descarga (19)_2.jpg)
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(t * 0.14);
      const bars = 80;
      for (let i = 0; i < bars; i++) {
        const ang = (i / bars) * Math.PI * 2;
        const wave =
          Math.abs(Math.sin(i * 0.38 + t * 4.5) * Math.cos(i * 0.22 - t * 2.8)) *
          (status === "idle" ? 14 : 32);
        const rStart = 66;
        const rEnd = rStart + 5 + wave;
        ctx.beginPath();
        ctx.moveTo(Math.cos(ang) * rStart, Math.sin(ang) * rStart);
        ctx.lineTo(Math.cos(ang) * rEnd, Math.sin(ang) * rEnd);
        ctx.strokeStyle = i % 4 === 0 ? `rgba(${accentRGB}, 0.9)` : `rgba(${primaryRGB}, 0.85)`;
        ctx.lineWidth = 2.2;
        ctx.stroke();
      }
      ctx.restore();

      // 6. Arcos de Turbina Pesada + Triángulos Direccionales
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(-t * 0.65);
      ctx.strokeStyle = `rgba(${primaryRGB}, 0.95)`;
      ctx.lineWidth = 6.5;
      ctx.beginPath();
      ctx.arc(0, 0, 58, 0.18, 1.45);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(0, 0, 58, Math.PI + 0.18, Math.PI + 1.45);
      ctx.stroke();
      ctx.restore();

      // 7. Enjambre de Partículas Cuánticas
      particles.forEach((p) => {
        p.angle += p.speed * speedMult;
        const pr = plasmaRadius + p.radiusOffset + Math.sin(t * 2.2 + p.angle) * 5;
        const px = cx + Math.cos(p.angle) * pr;
        const py = cy + Math.sin(p.angle) * pr;
        ctx.beginPath();
        ctx.arc(px, py, p.size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${primaryRGB}, ${p.alpha})`;
        ctx.fill();
      });

      // 8. Corazón del Reactor Arc
      const corePulse = 28 + Math.sin(t * 3.8) * (status === "idle" ? 4 : 10);
      const coreGrad = ctx.createRadialGradient(cx, cy, 3, cx, cy, corePulse + 24);
      coreGrad.addColorStop(0, "rgba(255, 255, 255, 1)");
      coreGrad.addColorStop(0.35, `rgba(${primaryRGB}, 0.95)`);
      coreGrad.addColorStop(0.72, `rgba(${secondaryRGB}, 0.45)`);
      coreGrad.addColorStop(1, "rgba(0, 0, 0, 0)");

      ctx.fillStyle = coreGrad;
      ctx.beginPath();
      ctx.arc(cx, cy, corePulse + 24, 0, Math.PI * 2);
      ctx.fill();

      // Anillo óptico central
      ctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.arc(cx, cy, 16, 0, Math.PI * 2);
      ctx.stroke();

      ctx.restore();
      animationId = requestAnimationFrame(render);
    };

    render();
    return () => cancelAnimationFrame(animationId);
  }, [status]);

  const dimClasses =
    size === "hero"
      ? "w-[260px] h-[260px] sm:w-[300px] sm:h-[300px] xl:w-[330px] xl:h-[330px]"
      : "w-[220px] h-[220px]";

  return (
    <div
      onClick={onClick}
      className="relative flex items-center justify-center w-full cursor-pointer select-none group"
    >
      {/* Ecualizador Lateral Izquierdo */}
      <div className="hidden sm:flex items-center gap-[3px] mr-2 opacity-85 group-hover:opacity-100 transition-opacity">
        {[22, 42, 28, 60, 78, 46, 92, 64, 36, 78, 98, 52].map((h, idx) => (
          <span
            key={`l-${idx}`}
            className="w-[3px] rounded-full bg-gradient-to-t from-cyber-purple via-cyber-cyan to-white animate-pulse"
            style={{
              height: `${status === "idle" ? Math.max(10, h * 0.48) : h}px`,
              animationDelay: `${idx * 85}ms`,
              animationDuration: status === "idle" ? "2s" : "0.5s",
            }}
          />
        ))}
      </div>

      {/* Contenedor Principal del Orbe Reactor */}
      <div className={`relative flex items-center justify-center ${dimClasses}`}>
        {/* Vectores FUI de Telemetría en las 4 esquinas */}
        <svg
          viewBox="0 0 360 360"
          className="absolute inset-0 w-full h-full pointer-events-none opacity-85 group-hover:opacity-100 transition-opacity duration-300"
        >
          <g stroke="#00E5FF" strokeWidth="1.2" fill="none" opacity="0.75">
            <polyline points="55,82 26,52 2,52" />
            <circle cx="55" cy="82" r="3.5" fill="#00E5FF" />
            <text x="4" y="44" fill="#00E5FF" fontSize="9" fontFamily="monospace" letterSpacing="1.2">
              ARC.CORE // 60FPS
            </text>

            <polyline points="305,82 334,52 358,52" />
            <circle cx="305" cy="82" r="3.5" fill="#00E5FF" />
            <text x="255" y="44" fill="#00E5FF" fontSize="9" fontFamily="monospace" letterSpacing="1.2">
              HAIKU-4.5
            </text>

            <polyline points="55,278 26,308 2,308" />
            <circle cx="55" cy="278" r="3.5" fill="#8B5CF6" />
            <text x="4" y="322" fill="#8B5CF6" fontSize="9" fontFamily="monospace" letterSpacing="1.2">
              SUPABASE.LIVE
            </text>

            <polyline points="305,278 334,308 358,308" />
            <circle cx="305" cy="278" r="3.5" fill="#00E5FF" />
            <text x="262" y="322" fill="#00E5FF" fontSize="9" fontFamily="monospace" letterSpacing="1.2">
              VOICE.READY
            </text>
          </g>
        </svg>

        <canvas
          ref={canvasRef}
          width={350}
          height={350}
          className="w-full h-full drop-shadow-[0_0_35px_rgba(0,229,255,0.65)] group-hover:scale-105 transition-transform duration-300"
        />
      </div>

      {/* Ecualizador Lateral Derecho */}
      <div className="hidden sm:flex items-center gap-[3px] ml-2 opacity-85 group-hover:opacity-100 transition-opacity">
        {[52, 98, 78, 36, 64, 92, 46, 78, 60, 28, 42, 22].map((h, idx) => (
          <span
            key={`r-${idx}`}
            className="w-[3px] rounded-full bg-gradient-to-t from-cyber-purple via-cyber-cyan to-white animate-pulse"
            style={{
              height: `${status === "idle" ? Math.max(10, h * 0.48) : h}px`,
              animationDelay: `${idx * 85}ms`,
              animationDuration: status === "idle" ? "2s" : "0.5s",
            }}
          />
        ))}
      </div>
    </div>
  );
}