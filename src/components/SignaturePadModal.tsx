"use client";
import React, { useRef, useState, useEffect } from "react";
import { X, Eraser, Check } from "lucide-react";

interface SignaturePadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (signatureDataUrl: string) => void;
}

export default function SignaturePadModal({ isOpen, onClose, onSave }: SignaturePadModalProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [isDrawing, setIsDrawing] = useState(false);

  useEffect(() => {
    if (isOpen && canvasRef.current) {
      const canvas = canvasRef.current;
      const ctx = canvas.getContext("2d");
      if (ctx) {
        // Fondo blanco obligatorio para exportar a PDF sin transparencias negras
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.strokeStyle = "#040711";
        ctx.lineWidth = 3;
        ctx.lineCap = "round";
      }
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const getCoordinates = (e: React.MouseEvent<HTMLCanvasElement> | React.TouchEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    if ('touches' in e) {
      return { 
        x: e.touches[0].clientX - rect.left, 
        y: e.touches[0].clientY - rect.top 
      };
    }
    return { x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY };
  };

  const startDrawing = (e: React.MouseEvent<HTMLCanvasElement> | React.TouchEvent<HTMLCanvasElement>) => {
    setIsDrawing(true);
    const { x, y } = getCoordinates(e);
    const ctx = canvasRef.current?.getContext("2d");
    if (ctx) {
      ctx.beginPath();
      ctx.moveTo(x, y);
    }
  };

  const draw = (e: React.MouseEvent<HTMLCanvasElement> | React.TouchEvent<HTMLCanvasElement>) => {
    if (!isDrawing) return;
    if (e.cancelable) e.preventDefault(); // Evita que la pantalla haga scroll en el celular al firmar
    const { x, y } = getCoordinates(e);
    const ctx = canvasRef.current?.getContext("2d");
    if (ctx) {
      ctx.lineTo(x, y);
      ctx.stroke();
    }
  };

  const stopDrawing = () => {
    setIsDrawing(false);
    const ctx = canvasRef.current?.getContext("2d");
    if (ctx) ctx.closePath();
  };

  const handleClear = () => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (canvas && ctx) {
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }
  };

  const handleSave = () => {
    if (canvasRef.current) {
      const dataUrl = canvasRef.current.toDataURL("image/png");
      onSave(dataUrl);
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
      <div className="w-full max-w-md bg-cyber-panel border border-white/10 rounded-2xl shadow-2xl overflow-hidden liquid-glass-dark">
        <div className="flex items-center justify-between p-4 border-b border-white/5">
          <h3 className="text-lg font-semibold text-cyber-cyan">Firma del Cliente</h3>
          <button onClick={onClose} className="p-1 text-slate-400 hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>
        
        <div className="p-5 flex flex-col items-center">
          <p className="text-sm text-slate-400 mb-4 text-center">
            Utiliza el dedo o el ratón para trazar la firma de conformidad.
          </p>
          <canvas
            ref={canvasRef}
            width={340}
            height={200}
            className="bg-white rounded-lg cursor-crosshair touch-none shadow-inner w-full max-w-[340px]"
            onMouseDown={startDrawing}
            onMouseMove={draw}
            onMouseUp={stopDrawing}
            onMouseLeave={stopDrawing}
            onTouchStart={startDrawing}
            onTouchMove={draw}
            onTouchEnd={stopDrawing}
          />
        </div>

        <div className="flex gap-3 p-4 bg-black/30 border-t border-white/5">
          <button
            onClick={handleClear}
            className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl border border-white/10 text-slate-300 hover:bg-white/5 transition-colors"
          >
            <Eraser size={18} />
            Borrar
          </button>
          <button
            onClick={handleSave}
            className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl bg-cyber-cyan text-black font-semibold hover:bg-cyber-cyan/90 transition-colors shadow-[0_0_15px_rgba(0,229,255,0.4)]"
          >
            <Check size={18} />
            Guardar
          </button>
        </div>
      </div>
    </div>
  );
}