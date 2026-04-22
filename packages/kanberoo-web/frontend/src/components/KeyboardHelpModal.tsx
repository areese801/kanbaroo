import type { JSX } from 'react';
import Modal from './Modal';

type Shortcut = {
  key: string;
  action: string;
};

const SHORTCUTS: Shortcut[] = [
  { key: 'n', action: 'New story (on the board)' },
  { key: '/', action: 'Focus the board search' },
  { key: 'e', action: 'Edit the story (on story detail)' },
  { key: '?', action: 'Show this shortcut list' },
  { key: 'Escape', action: 'Close a modal, exit edit mode, or clear search' },
];

export type KeyboardHelpModalProps = {
  onClose: () => void;
};

export default function KeyboardHelpModal({
  onClose,
}: KeyboardHelpModalProps): JSX.Element {
  return (
    <Modal labelledBy="keyboard-help-heading" onClose={onClose}>
      <h2 id="keyboard-help-heading">Keyboard shortcuts</h2>
      <table className="keyboard-help-table">
        <thead>
          <tr>
            <th scope="col">Key</th>
            <th scope="col">Action</th>
          </tr>
        </thead>
        <tbody>
          {SHORTCUTS.map((shortcut) => (
            <tr key={shortcut.key}>
              <td>
                <kbd>{shortcut.key}</kbd>
              </td>
              <td>{shortcut.action}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="modal-actions">
        <button type="button" onClick={onClose}>
          Close
        </button>
      </div>
    </Modal>
  );
}
