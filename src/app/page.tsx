import { Button } from "@/components/ui/button";
import { brand } from "../../branding.config";

export default function Home() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 px-6 py-24 text-center">
      <span className="bg-brand-accent text-brand-accent-foreground rounded-full px-3 py-1 text-sm font-medium">
        Section 1 — project bootstrap
      </span>
      <h1 className="max-w-xl text-4xl font-semibold tracking-tight">{brand.fullName}</h1>
      <p className="text-muted-foreground max-w-md text-lg">{brand.tagline}</p>
      <Button>Primary action</Button>
    </div>
  );
}
