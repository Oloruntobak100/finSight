import { BooksDateRange } from "@/components/books/books-date-range";
import { BooksNav } from "@/components/books/books-nav";

export default function BooksLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-4">
      <BooksDateRange />
      <BooksNav />
      {children}
    </div>
  );
}
