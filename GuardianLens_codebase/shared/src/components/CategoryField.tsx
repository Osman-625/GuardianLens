// Category input shared by the website's manual form and the extension's Review state.
// It is FREE TEXT: the 12 categories the models were trained on are only offered as
// suggestions (a datalist), and any other category is accepted. When the text is not a
// trained category, a plain note explains that the price comparison uses the overall average.
import { isTrainedCategory, TRAINED_CATEGORIES } from "../categories";
import { UNSEEN_CATEGORY_NOTE } from "../copy";

/** Props of the category input; `value` is the current text and `onChange` receives each edit. */
export interface CategoryFieldProps {
  /** Unique id; the label, the suggestion list, and the note are all derived from it. */
  id: string;
  value: string;
  onChange(value: string): void;
  /** A validation or server error to show under the field. */
  error?: string | null;
}

/** A labelled, free-text category input with the trained categories as suggestions. */
export function CategoryField({ id, value, onChange, error }: CategoryFieldProps) {
  const listId = `${id}-suggestions`;
  const noteId = `${id}-note`;
  const errorId = `${id}-error`;
  const showNote = value.trim() !== "" && !isTrainedCategory(value);
  // The input is described by whichever of the note and the error are on screen.
  const describedBy = [showNote ? noteId : null, error ? errorId : null].filter(Boolean).join(" ");

  return (
    <div className="field">
      <label htmlFor={id}>Category</label>
      <input
        id={id}
        list={listId}
        value={value}
        maxLength={80}
        autoComplete="off"
        placeholder="Choose or type a category"
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
      />
      <datalist id={listId}>
        {TRAINED_CATEGORIES.map((category) => (
          <option key={category} value={category} />
        ))}
      </datalist>
      {showNote && (
        <span className="helper" id={noteId}>
          {UNSEEN_CATEGORY_NOTE}
        </span>
      )}
      {/* role="alert" so screen readers announce the error, not only sighted users who see red text. */}
      {error && (
        <span className="error-text" id={errorId} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
