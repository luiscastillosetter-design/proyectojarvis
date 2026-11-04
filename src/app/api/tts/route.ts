import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const text = searchParams.get("text") || "";
    const clean = text.replace(/[*_#`~>•]/g, "").trim().slice(0, 1000);

    if (!clean) {
      return new Response("Texto vacío", { status: 400 });
    }

    const voice = "es-MX-JorgeNeural";
    const edgeEndpoint = `https://tts.cybernex.workers.dev/?text=${encodeURIComponent(clean)}&voice=${voice}`;
    const ttsGoogle = `https://translate.google.com/translate_tts?ie=UTF-8&q=${encodeURIComponent(clean)}&tl=es&client=tw-ob`;

    let arrayBuffer: ArrayBuffer;
    try {
      const res = await fetch(edgeEndpoint, { headers: { "User-Agent": "Mozilla/5.0" } });
      if (!res.ok) throw new Error("Fallback necesario");
      arrayBuffer = await res.arrayBuffer();
    } catch {
      const res = await fetch(ttsGoogle, { headers: { "User-Agent": "Mozilla/5.0" } });
      arrayBuffer = await res.arrayBuffer();
    }

    const audioBlob = new Blob([arrayBuffer], { type: "audio/mpeg" });

    return new Response(audioBlob, {
      status: 200,
      headers: {
        "Content-Type": "audio/mpeg",
        "Cache-Control": "public, max-age=3600",
      },
    });
  } catch (error) {
    return new Response("Error en síntesis", { status: 500 });
  }
}
