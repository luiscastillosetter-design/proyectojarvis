import { NextRequest, NextResponse } from "next/server";
import { MsEdgeTTS, OUTPUT_FORMAT } from "msedge-tts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const text = searchParams.get("text") || "";
    const clean = text.replace(/[*_#`~>•]/g, "").trim().slice(0, 1000);

    if (!clean) return new NextResponse("Texto vacío", { status: 400 });

    const tts = new MsEdgeTTS();
    await tts.setMetadata("es-MX-JorgeNeural", OUTPUT_FORMAT.AUDIO_24KHZ_48KBITRATE_MONO_MP3);
    const result = await tts.toStream(clean);
    const stream = (result as any).audioStream || result;

    const chunks: Buffer[] = [];
    await new Promise<void>((resolve, reject) => {
      stream.on("data", (chunk: Buffer) => chunks.push(chunk));
      stream.on("end", () => resolve());
      stream.on("error", (err: any) => reject(err));
    });

    return new NextResponse(Buffer.concat(chunks), {
      status: 200,
      headers: {
        "Content-Type": "audio/mpeg",
        "Cache-Control": "public, max-age=3600",
      },
    });
  } catch (error: any) {
    return new NextResponse("Error en síntesis", { status: 500 });
  }
}
