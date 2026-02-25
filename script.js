class JemiChatUI {
    constructor() {
        this.body = document.body;
        this.page = this.body ? this.body.dataset.page : '';
        this.themeToggleBtn = document.getElementById('themeToggleBtn');
        this.composeBtn = document.getElementById('floatingComposeBtn');
        this.modal = document.getElementById('composerModal');
        this.closeBtn = document.getElementById('composerCloseBtn');
        this.form = document.getElementById('chatForm');
        this.fileInput = document.getElementById('fileInput');
        this.messageInput = document.getElementById('messageInput');
        this.emojiToggleBtn = document.getElementById('emojiToggleBtn');
        this.emojiPicker = document.getElementById('emojiPicker');
        this.previewContainer = document.getElementById('filePreviewContainer');
        this.drawer = document.getElementById('conversationDrawer');
        this.drawerToggle = document.getElementById('conversationDrawerToggle');
        this.drawerBackdrop = document.getElementById('conversationDrawerBackdrop');
        this.welcomeLoader = document.getElementById('chatWelcomeLoader');
        this.conversationSkeleton = document.getElementById('conversationSkeleton');
        this.imagePreviewModal = document.getElementById('imagePreviewModal');
        this.imagePreviewClose = document.getElementById('imagePreviewClose');
        this.imagePreviewBackdrop = this.imagePreviewModal ? this.imagePreviewModal.querySelector('.image-preview-backdrop') : null;
        this.imagePreviewFull = document.getElementById('imagePreviewFull');
        this.imagePreviewDownload = document.getElementById('imagePreviewDownload');

        this.dragState = {
            active: false,
            moved: false,
            startX: 0,
            startY: 0,
            left: 0,
            top: 0
        };
    }

    init() {
        this.setupThemeToggle();
        this.setupWelcomeLoader();
        this.setupDrawer();
        this.bindPasswordToggles();
        this.bindCopyButtons();
        this.bindImagePreview();
        this.bindMessageEditing();
        this.bindComposer();
        this.bindEmojiPicker();
        this.bindFileInput();
        this.bindFormValidation();
        this.scrollChatToBottom();

        window.setTimeout(() => {
            this.body.classList.remove('ui-preload');
            if (this.conversationSkeleton) {
                this.conversationSkeleton.classList.add('hidden');
            }
        }, 320);
    }

    setupThemeToggle() {
        const updateThemeIcon = () => {
            if (!this.themeToggleBtn) {
                return;
            }
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            this.themeToggleBtn.textContent = theme === 'dark' ? '☀' : '☾';
            this.themeToggleBtn.title = theme === 'dark' ? 'Passer en mode clair' : 'Passer en mode sombre';
        };

        updateThemeIcon();

        if (!this.themeToggleBtn) {
            return;
        }

        this.themeToggleBtn.addEventListener('click', () => {
            const current = document.documentElement.getAttribute('data-theme') || 'light';
            const next = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            try {
                localStorage.setItem('jemichat_theme', next);
            } catch (error) {
                // No-op
            }
            updateThemeIcon();
        });
    }

    setupWelcomeLoader() {
        if (this.page !== 'index' || !this.welcomeLoader) {
            return;
        }

        const key = 'jemichat_loader_until';
        let until = 0;
        try {
            until = parseInt(localStorage.getItem(key) || '0', 10) || 0;
        } catch (error) {
            until = 0;
        }

        const now = Date.now();
        if (until > now) {
            this.welcomeLoader.classList.add('hidden');
            return;
        }

        this.body.classList.add('loader-active');
        this.welcomeLoader.classList.remove('hidden');
        requestAnimationFrame(() => this.welcomeLoader.classList.add('visible'));

        try {
            localStorage.setItem(key, String(now + 3600 * 1000));
        } catch (error) {
            // No-op
        }

        window.setTimeout(() => {
            this.welcomeLoader.classList.remove('visible');
            this.welcomeLoader.classList.add('hidden');
            this.body.classList.remove('loader-active');
        }, 1700);
    }

    setupDrawer() {
        if (!this.drawer || !this.drawerToggle || !this.drawerBackdrop) {
            return;
        }

        this.drawerToggle.addEventListener('click', () => {
            this.body.classList.toggle('drawer-open');
        });

        this.drawerBackdrop.addEventListener('click', () => {
            this.body.classList.remove('drawer-open');
        });

        document.addEventListener('click', (event) => {
            const conversationItem = event.target.closest('.conversation-item');
            if (conversationItem) {
                this.body.classList.remove('drawer-open');
            }
        });

        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                this.body.classList.remove('drawer-open');
                this.closeComposer();
                this.closeImagePreview();
            }
        });
    }

    bindPasswordToggles() {
        document.addEventListener('click', (event) => {
            const toggle = event.target.closest('.password-toggle');
            if (!toggle) {
                return;
            }

            const targetId = toggle.getAttribute('data-target');
            const input = targetId ? document.getElementById(targetId) : null;
            if (!input) {
                return;
            }

            const isPassword = input.type === 'password';
            input.type = isPassword ? 'text' : 'password';
            toggle.textContent = isPassword ? '🙈' : '👁';
        });
    }

    bindCopyButtons() {
        document.addEventListener('click', (event) => {
            if (event.target.classList.contains('copy-btn')) {
                this.copyText(event.target);
            }
        });
    }

    bindImagePreview() {
        document.addEventListener('click', (event) => {
            const imageButton = event.target.closest('.image-thumb-btn');
            if (!imageButton || !this.imagePreviewModal || !this.imagePreviewFull || !this.imagePreviewDownload) {
                return;
            }

            const src = imageButton.getAttribute('data-image-src') || '';
            const name = imageButton.getAttribute('data-image-name') || 'Image';
            const downloadUrl = imageButton.getAttribute('data-download-url') || '#';

            this.imagePreviewFull.src = src;
            this.imagePreviewFull.alt = name;
            this.imagePreviewDownload.href = downloadUrl;
            this.imagePreviewModal.classList.remove('hidden');
            requestAnimationFrame(() => this.imagePreviewModal.classList.add('visible'));
        });

        if (this.imagePreviewClose) {
            this.imagePreviewClose.addEventListener('click', () => this.closeImagePreview());
        }
        if (this.imagePreviewBackdrop) {
            this.imagePreviewBackdrop.addEventListener('click', () => this.closeImagePreview());
        }
    }

    closeImagePreview() {
        if (!this.imagePreviewModal) {
            return;
        }

        this.imagePreviewModal.classList.remove('visible');
        window.setTimeout(() => {
            this.imagePreviewModal.classList.add('hidden');
            if (this.imagePreviewFull) {
                this.imagePreviewFull.src = '';
            }
        }, 180);
    }

    bindMessageEditing() {
        document.addEventListener('click', (event) => {
            const editBtn = event.target.closest('.message-edit-btn');
            if (editBtn) {
                const messageContent = editBtn.closest('.message-content');
                if (!messageContent) {
                    return;
                }

                const display = messageContent.querySelector('.message-display');
                const editForm = messageContent.querySelector('.message-edit-form');
                const textarea = editForm ? editForm.querySelector('textarea') : null;
                if (!display || !editForm) {
                    return;
                }

                display.classList.add('is-hidden');
                editForm.classList.remove('is-hidden');
                if (textarea) {
                    textarea.focus();
                    const end = textarea.value.length;
                    textarea.setSelectionRange(end, end);
                }
                return;
            }

            const cancelBtn = event.target.closest('.message-cancel-edit');
            if (cancelBtn) {
                const editForm = cancelBtn.closest('.message-edit-form');
                const messageContent = cancelBtn.closest('.message-content');
                const display = messageContent ? messageContent.querySelector('.message-display') : null;
                if (!editForm || !display) {
                    return;
                }

                editForm.classList.add('is-hidden');
                display.classList.remove('is-hidden');
            }
        });
    }

    bindComposer() {
        if (!this.composeBtn || !this.modal) {
            return;
        }

        this.composeBtn.addEventListener('pointerdown', (event) => this.startDrag(event));
        this.composeBtn.addEventListener('pointermove', (event) => this.onDrag(event));
        this.composeBtn.addEventListener('pointerup', (event) => this.endDrag(event));
        this.composeBtn.addEventListener('pointercancel', (event) => this.endDrag(event));

        if (this.closeBtn) {
            this.closeBtn.addEventListener('click', () => this.closeComposer());
        }

        const backdrop = this.modal.querySelector('.composer-backdrop');
        if (backdrop) {
            backdrop.addEventListener('click', () => this.closeComposer());
        }
    }

    startDrag(event) {
        event.preventDefault();
        this.dragState.active = true;
        this.dragState.moved = false;
        this.dragState.startX = event.clientX;
        this.dragState.startY = event.clientY;

        const rect = this.composeBtn.getBoundingClientRect();
        this.dragState.left = rect.left;
        this.dragState.top = rect.top;
        this.composeBtn.setPointerCapture(event.pointerId);
    }

    onDrag(event) {
        if (!this.dragState.active) {
            return;
        }

        const dx = event.clientX - this.dragState.startX;
        const dy = event.clientY - this.dragState.startY;
        if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
            this.dragState.moved = true;
        }

        if (!this.dragState.moved) {
            return;
        }

        const size = this.composeBtn.offsetWidth || 64;
        const maxLeft = window.innerWidth - size - 8;
        const maxTop = window.innerHeight - size - 8;

        const newLeft = Math.min(Math.max(this.dragState.left + dx, 8), maxLeft);
        const newTop = Math.min(Math.max(this.dragState.top + dy, 8), maxTop);

        this.composeBtn.style.left = newLeft + 'px';
        this.composeBtn.style.top = newTop + 'px';
        this.composeBtn.style.right = 'auto';
        this.composeBtn.style.bottom = 'auto';
    }

    endDrag(event) {
        if (!this.dragState.active) {
            return;
        }

        this.dragState.active = false;
        if (this.composeBtn.hasPointerCapture(event.pointerId)) {
            this.composeBtn.releasePointerCapture(event.pointerId);
        }

        if (!this.dragState.moved) {
            this.openComposer();
        }
    }

    openComposer() {
        this.modal.classList.remove('hidden');
        requestAnimationFrame(() => {
            this.modal.classList.add('visible');
            if (this.messageInput) {
                this.messageInput.focus();
            }
        });
    }

    closeComposer() {
        if (!this.modal) {
            return;
        }

        this.closeEmojiPicker();
        this.modal.classList.remove('visible');
        window.setTimeout(() => {
            this.modal.classList.add('hidden');
        }, 160);
    }

    bindEmojiPicker() {
        if (!this.emojiToggleBtn || !this.emojiPicker || !this.messageInput) {
            return;
        }

        this.emojiToggleBtn.addEventListener('click', (event) => {
            event.preventDefault();
            this.emojiPicker.classList.toggle('is-hidden');
        });

        this.emojiPicker.addEventListener('click', (event) => {
            const emojiBtn = event.target.closest('.emoji-item');
            if (!emojiBtn) {
                return;
            }

            const emoji = emojiBtn.getAttribute('data-emoji') || '';
            if (emoji === '') {
                return;
            }

            this.insertEmojiAtCursor(emoji);
        });

        document.addEventListener('click', (event) => {
            if (this.emojiPicker.classList.contains('is-hidden')) {
                return;
            }
            if (event.target.closest('#emojiPicker') || event.target.closest('#emojiToggleBtn')) {
                return;
            }
            this.closeEmojiPicker();
        });
    }

    closeEmojiPicker() {
        if (!this.emojiPicker) {
            return;
        }
        this.emojiPicker.classList.add('is-hidden');
    }

    insertEmojiAtCursor(emoji) {
        if (!this.messageInput) {
            return;
        }

        const input = this.messageInput;
        const value = input.value || '';
        const start = typeof input.selectionStart === 'number' ? input.selectionStart : value.length;
        const end = typeof input.selectionEnd === 'number' ? input.selectionEnd : value.length;
        input.value = value.slice(0, start) + emoji + value.slice(end);
        const nextCursor = start + emoji.length;
        input.focus();
        input.setSelectionRange(nextCursor, nextCursor);
    }

    bindFileInput() {
        if (!this.fileInput) {
            return;
        }

        this.fileInput.addEventListener('change', (event) => {
            const files = event.target.files;
            if (files && files.length > 0) {
                this.showFilePreview(files[0]);
            } else {
                this.removeFilePreview();
            }
        });
    }

    bindFormValidation() {
        if (!this.form) {
            return;
        }

        this.form.addEventListener('submit', (event) => {
            const hasFile = this.fileInput && this.fileInput.files.length > 0;
            const hasMessage = this.messageInput && this.messageInput.value.trim().length > 0;

            if (!hasFile && !hasMessage) {
                event.preventDefault();
                return;
            }
            const submitBtn = this.form.querySelector('.composer-icon-btn.send');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.classList.add('loading');
                submitBtn.textContent = '...';
            }
        });
    }

    showFilePreview(file) {
        if (!this.previewContainer) {
            return;
        }

        this.previewContainer.innerHTML = `
            <div class="file-preview">
                <div class="file-preview-header">
                    <div class="file-preview-icon">${this.getFileIcon(file.type)}</div>
                    <div class="file-preview-info">
                        <div class="file-preview-name">${this.escapeHtml(file.name)}</div>
                        <div class="file-preview-size">${this.formatFileSize(file.size)}</div>
                    </div>
                    <button type="button" class="file-preview-remove" id="removePreviewBtn">×</button>
                </div>
            </div>
        `;

        const removeBtn = document.getElementById('removePreviewBtn');
        if (removeBtn) {
            removeBtn.addEventListener('click', () => this.removeFilePreview());
        }
    }

    removeFilePreview() {
        if (this.fileInput) {
            this.fileInput.value = '';
        }
        if (this.previewContainer) {
            this.previewContainer.innerHTML = '';
        }
    }

    copyText(button) {
        const messageText = button.closest('.message-text');
        if (!messageText) {
            return;
        }

        const content = messageText.querySelector('.message-text-content');
        if (!content) {
            return;
        }

        const textToCopy = content.textContent || '';
        const originalText = button.textContent;

        navigator.clipboard.writeText(textToCopy).then(() => {
            button.textContent = 'OK';
            setTimeout(() => {
                button.textContent = originalText;
            }, 1200);
        }).catch(() => {
            const textArea = document.createElement('textarea');
            textArea.value = textToCopy;
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);

            button.textContent = 'OK';
            setTimeout(() => {
                button.textContent = originalText;
            }, 1200);
        });
    }

    getFileIcon(mimeType) {
        if ((mimeType || '').startsWith('image/')) {
            return '🖼️';
        }
        if (mimeType === 'application/pdf') {
            return '📄';
        }
        if ((mimeType || '').includes('word')) {
            return '📝';
        }
        if ((mimeType || '').includes('excel') || (mimeType || '').includes('sheet')) {
            return '📊';
        }
        if ((mimeType || '').includes('zip')) {
            return '📦';
        }
        return '📁';
    }

    formatFileSize(bytes) {
        if (bytes === 0) {
            return '0 B';
        }
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    scrollChatToBottom() {
        const chatMessages = document.getElementById('chatMessages');
        if (chatMessages) {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const ui = new JemiChatUI();
    ui.init();
});
