# spotify_button.py
import pygame
import webbrowser

class SpotifyButton:
    """
    En enkel Spotify-knapp med dropdown.
    - options: lista av (namn, url/uri). Ex: ("Lo-fi Beats", "https://open.spotify.com/playlist/xyz")
      Du kan även använda 'spotify:playlist:...' eller 'spotify:track:...'.
    - pos: mittenposition (x, y) för själva knappen.
    """
    def __init__(self, pos, options=None, width=200, font=None):
        self.width = width
        self.height = 40
        self.pos = pos
        self.button_rect = pygame.Rect(0, 0, self.width, self.height)
        self.button_rect.center = pos

        self.options = options or [
            ("Open Spotify", "https://open.spotify.com/"),
            ("Today's Top Hits", "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"),
            ("Lo-Fi Beats", "https://open.spotify.com/playlist/1h0CEZCm6IbFTbxThn6Xcs"),
        ]
        self.opened = False
        self.hover_index = -1

        self.font = font or pygame.font.SysFont(None, 24)
        self.small = pygame.font.SysFont(None, 22)

        # enkel klick-debounce
        self._last_click_ms = 0
        self._debounce_ms = 140

    def _draw_button(self, screen):
        # Bas-knapp
        bg = (25, 25, 25)
        border = (60, 60, 60)
        txt = (230, 230, 230)

        pygame.draw.rect(screen, bg, self.button_rect, border_radius=10)
        pygame.draw.rect(screen, border, self.button_rect, width=2, border_radius=10)

        label = self.font.render("Spotify", True, txt)
        screen.blit(label, label.get_rect(center=self.button_rect.center))

        # liten pil för dropdown
        tri_x = self.button_rect.right - 18
        cy = self.button_rect.centery
        pts = [(tri_x-8, cy-4), (tri_x+4, cy-4), (tri_x-2, cy+6)] if not self.opened else \
              [(tri_x-8, cy+4), (tri_x+4, cy+4), (tri_x-2, cy-6)]
        pygame.draw.polygon(screen, txt, pts)

    def _dropdown_rects(self):
        # rektanglar för varje alternativ under knappen
        rects = []
        x = self.button_rect.left
        y = self.button_rect.bottom + 6
        item_h = 34
        for _ in self.options:
            rects.append(pygame.Rect(x, y, self.width, item_h))
            y += item_h + 2
        return rects

    def _draw_dropdown(self, screen):
        bg = (15, 15, 15)
        border = (60, 60, 60)
        txt = (230, 230, 230)
        hover_bg = (35, 35, 35)

        for idx, r in enumerate(self._dropdown_rects()):
            pygame.draw.rect(screen, hover_bg if idx == self.hover_index else bg, r, border_radius=8)
            pygame.draw.rect(screen, border, r, width=1, border_radius=8)
            name = self.small.render(self.options[idx][0], True, txt)
            screen.blit(name, name.get_rect(midleft=(r.left + 10, r.centery)))

    def update(self, mouse_pos, events):
        """Kalla varje frame. Returnerar True om UI:n fångade ett klick."""
        now = pygame.time.get_ticks()
        consumed = False

        # hover i dropdown
        self.hover_index = -1
        if self.opened:
            for i, r in enumerate(self._dropdown_rects()):
                if r.collidepoint(mouse_pos):
                    self.hover_index = i
                    break

        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if now - self._last_click_ms < self._debounce_ms:
                    continue
                self._last_click_ms = now

                # Klick på huvudknappen
                if self.button_rect.collidepoint(mouse_pos):
                    self.opened = not self.opened
                    consumed = True
                elif self.opened:
                    # Klick i dropdown
                    rects = self._dropdown_rects()
                    for i, r in enumerate(rects):
                        if r.collidepoint(mouse_pos):
                            self._on_select(i)
                            consumed = True
                            break
                    else:
                        # klick utanför stänger men släpper inte igenom
                        self.opened = False

        return consumed

    def _on_select(self, idx):
        name, url = self.options[idx]
        # Mute/pausa spelmusiken så att Spotify får utrymme
        try:
            pygame.mixer.music.set_volume(0.0)
        except Exception:
            pass
        self.opened = False
        # Öppna Spotify (web/app). Systemet styr om appen tar över.
        webbrowser.open(url, new=1)

    def draw(self, screen):
        self._draw_button(screen)
        if self.opened:
            self._draw_dropdown(screen)
