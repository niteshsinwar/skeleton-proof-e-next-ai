// The component catalogue's route (03/F52). Off unless APP_CATALOGUE=1 (development and tests).
import { notFound } from "next/navigation";

import { Catalogue } from "@/components/catalogue";

export const dynamic = "force-dynamic";

export default function CataloguePage() {
  if (process.env.APP_CATALOGUE !== "1") notFound();
  return <Catalogue />;
}
