import Image from "next/image";

export function Logo({ size = 32 }: { size?: number }) {
  return <Image src="/icons/icon.svg" alt="" width={size} height={size} unoptimized priority />;
}
