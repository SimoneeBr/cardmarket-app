import Link from "next/link";

export default function NotFound() {
  return (
    <div className="grid min-h-dvh place-items-center p-6 text-center">
      <div>
        <p className="text-5xl">🃏</p>
        <h1 className="mt-2 text-xl font-bold">Pagina non trovata</h1>
        <Link href="/" className="btn-primary mt-4">
          Torna alla dashboard
        </Link>
      </div>
    </div>
  );
}
