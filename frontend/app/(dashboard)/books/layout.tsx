import { BooksNav } from "@/components/books/books-nav";

export default function BooksLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="space-y-6">
      <BooksNav />
      {children}
    </div>
  );
}
