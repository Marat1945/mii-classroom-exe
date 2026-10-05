# -*- coding: utf-8 -*-
"""
Языки интерфейса «Кода Марса»: русский, украинский, польский, английский.
Ключ перевода — русский текст; T("...") возвращает его на выбранном языке.
"""
from __future__ import annotations

LANGS = [("ru", "Русский", "Язык"), ("uk", "Українська", "Мова"),
         ("pl", "Polski", "Język"), ("en", "English", "Language")]
_ORDER = {"uk": 0, "pl": 1, "en": 2}
_lang = "ru"

# русский текст: (украинский, польский, английский)
TR = {
    "Код Марса": ("Код Марса", "Kod Marsa", "Mars Code"),
    "Справка": ("Довідка", "Pomoc", "Help"),
    "Язык": ("Мова", "Język", "Language"),
    "Справка — Код Марса": ("Довідка — Код Марса", "Pomoc — Kod Marsa", "Help — Mars Code"),
    "Настройка азбуки Морзе": ("Налаштування абетки Морзе", "Ustawienia alfabetu Morse’a", "Morse code settings"),
    "Сообщение": ("Повідомлення", "Wiadomość", "Message"),
    "Очистить всё": ("Очистити все", "Wyczyść wszystko", "Clear all"),
    "Напишите сообщение и нажмите Enter. Расшифрованный текст тоже появляется здесь.":
        ("Напишіть повідомлення й натисніть Enter. Розшифрований текст теж з’являється тут.",
         "Napisz wiadomość i naciśnij Enter. Odszyfrowany tekst też pojawia się tutaj.",
         "Type a message and press Enter. Decrypted text also appears here."),
    "Shift+Enter переносит строку. Если удерживать Backspace 2 секунды, очистятся все поля.":
        ("Shift+Enter переносить рядок. Якщо утримувати Backspace 2 секунди, очистяться всі поля.",
         "Shift+Enter przenosi wiersz. Przytrzymanie Backspace przez 2 sekundy czyści wszystkie pola.",
         "Shift+Enter starts a new line. Holding Backspace for 2 seconds clears all fields."),
    "Ключ": ("Ключ", "Klucz", "Key"),
    "Выбрать ключ": ("Обрати ключ", "Wybierz klucz", "Choose key"),
    "Ключ-фраза": ("Ключ-фраза", "Fraza-klucz", "Key phrase"),
    "Автокод: каждый день выбирается ключ с номером текущего числа, как на телефоне. Если сообщение "
    "зашифровано ключом другого дня, программа подберёт ключ сама.":
        ("Автокод: щодня обирається ключ із номером поточного числа, як на телефоні. Якщо повідомлення "
         "зашифроване ключем іншого дня, програма підбере ключ сама.",
         "Autokod: każdego dnia wybierany jest klucz o numerze bieżącego dnia, jak w telefonie. Jeśli wiadomość "
         "zaszyfrowano kluczem innego dnia, program sam dobierze klucz.",
         "Auto-code: each day the key with today's day number is selected, as on the phone. If a message was "
         "encrypted with another day's key, the program finds that key itself."),
    "Введите ключ-фразу": ("Введіть ключ-фразу", "Wpisz frazę-klucz", "Enter the key phrase"),
    "HEX-ключ:": ("HEX-ключ:", "Klucz HEX:", "HEX key:"),
    "Копировать": ("Копіювати", "Kopiuj", "Copy"),
    "Вставить": ("Вставити", "Wklej", "Paste"),
    "Ключ вычисляется из фразы через SHA-256 так же, как на телефоне. У получателя должна быть та же фраза.":
        ("Ключ обчислюється з фрази через SHA-256 так само, як на телефоні. В отримувача має бути та сама фраза.",
         "Klucz jest obliczany z frazy przez SHA-256 tak samo jak w telefonie. Odbiorca musi mieć tę samą frazę.",
         "The key is derived from the phrase with SHA-256, exactly as on the phone. The recipient needs the same phrase."),
    "Зашифровать": ("Зашифрувати", "Zaszyfruj", "Encrypt"),
    "Расшифровать": ("Розшифрувати", "Odszyfruj", "Decrypt"),
    "Универсальный": ("Універсальний", "Uniwersalny", "Universal"),
    "Код {n}": ("Код {n}", "Kod {n}", "Code {n}"),
    "пустая ключ-фраза": ("порожня ключ-фраза", "pusta fraza-klucz", "empty key phrase"),
    "Шифровка Base32": ("Шифровка Base32", "Szyfrogram Base32", "Cipher text Base32"),
    "Здесь появится шифровка. Чтобы расшифровать сообщение, вставьте сюда его шифровку: программа расшифрует её сама.":
        ("Тут з’явиться шифровка. Щоб розшифрувати повідомлення, вставте сюди його шифровку: програма розшифрує її сама.",
         "Tu pojawi się szyfrogram. Aby odszyfrować wiadomość, wklej tu jej szyfrogram: program odszyfruje go sam.",
         "The cipher text appears here. To decrypt a message, paste its cipher text here and the program decrypts it."),
    "Азбука Морзе": ("Абетка Морзе", "Alfabet Morse’a", "Morse code"),
    "Настройка\nазбуки Морзе": ("Налаштування\nабетки Морзе", "Ustawienia\nalfabetu Morse’a", "Morse\nsettings"),
    "Морзянка появится после шифрования. Сюда можно вставить принятую морзянку или написать текст и нажать Enter.":
        ("Морзянка з’явиться після шифрування. Сюди можна вставити прийняту морзянку або написати текст і натиснути Enter.",
         "Kod Morse’a pojawi się po zaszyfrowaniu. Można tu wkleić odebrany kod albo wpisać tekst i nacisnąć Enter.",
         "Morse code appears after encryption. Paste received Morse here, or type text and press Enter."),
    "Здесь появится QR-код.\nЧтобы расшифровать картинку с QR, перетащите её в окно или нажмите «Открыть QR».":
        ("Тут з’явиться QR-код.\nЩоб розшифрувати картинку з QR, перетягніть її у вікно або натисніть «Відкрити QR».",
         "Tu pojawi się kod QR.\nAby odszyfrować obraz z kodem QR, przeciągnij go do okna lub naciśnij „Otwórz QR”.",
         "The QR code appears here.\nTo decrypt a QR picture, drag it into the window or press “Open QR”."),
    "Ключ: {key}": ("Ключ: {key}", "Klucz: {key}", "Key: {key}"),
    "Сохранить QR": ("Зберегти QR", "Zapisz QR", "Save QR"),
    "Копировать QR": ("Копіювати QR", "Kopiuj QR", "Copy QR"),
    "Открыть QR": ("Відкрити QR", "Otwórz QR", "Open QR"),
    "Бланк шифровки\npng": ("Бланк шифровки\npng", "Formularz\npng", "Cipher form\npng"),
    "Бланк шифровки\ndoc": ("Бланк шифровки\ndoc", "Formularz\ndoc", "Cipher form\ndoc"),
    "Передать SSTV": ("Передати SSTV", "Nadaj SSTV", "Send SSTV"),
    "Остановить SSTV": ("Зупинити SSTV", "Zatrzymaj SSTV", "Stop SSTV"),
    "Модель SSTV": ("Модель SSTV", "Tryb SSTV", "SSTV mode"),
    "Готовлю SSTV…": ("Готую SSTV…", "Przygotowuję SSTV…", "Preparing SSTV…"),
    "{name}  ·  {sec} с": ("{name}  ·  {sec} с", "{name}  ·  {sec} s", "{name}  ·  {sec} s"),
    "Сначала зашифруйте сообщение: SSTV передаёт QR-код":
        ("Спочатку зашифруйте повідомлення: SSTV передає QR-код", "Najpierw zaszyfruj wiadomość: SSTV nadaje kod QR",
         "Encrypt a message first: SSTV transmits the QR code"),
    "QR-код слишком мелкий для {mode}: выберите PD 120, PD 180, PD 240 или PD 290":
        ("QR-код задрібний для {mode}: оберіть PD 120, PD 180, PD 240 або PD 290",
         "Kod QR jest za drobny dla {mode}: wybierz PD 120, PD 180, PD 240 lub PD 290",
         "The QR code is too fine for {mode}: choose PD 120, PD 180, PD 240 or PD 290"),
    "Передача SSTV завершена": ("Передачу SSTV завершено", "Nadawanie SSTV zakończone", "SSTV transmission finished"),
    "Не удалось подготовить сигнал SSTV: {e}":
        ("Не вдалося підготувати сигнал SSTV: {e}", "Nie udało się przygotować sygnału SSTV: {e}",
         "Could not prepare the SSTV signal: {e}"),
    "Из файла…": ("З файлу…", "Z pliku…", "From file…"),
    "Из буфера обмена": ("З буфера обміну", "Ze schowka", "From clipboard"),
    "Найти на экране": ("Знайти на екрані", "Znajdź na ekranie", "Find on screen"),
    "Вырезать": ("Вирізати", "Wytnij", "Cut"),
    "Копировать всё": ("Копіювати все", "Kopiuj wszystko", "Copy all"),
    "Выделить всё": ("Виділити все", "Zaznacz wszystko", "Select all"),
    "Очистить поле": ("Очистити поле", "Wyczyść pole", "Clear field"),
    "Поделиться": ("Поділитися", "Udostępnij", "Share"),
    "Открыть QR из файла…": ("Відкрити QR з файлу…", "Otwórz QR z pliku…", "Open QR from file…"),
    "Вставить QR из буфера обмена": ("Вставити QR з буфера обміну", "Wklej QR ze schowka", "Paste QR from clipboard"),
    "Найти QR на экране": ("Знайти QR на екрані", "Znajdź QR na ekranie", "Find QR on screen"),
    "Бланк шифровки PNG": ("Бланк шифровки PNG", "Formularz PNG", "Cipher form PNG"),
    "Бланк шифровки Word": ("Бланк шифровки Word", "Formularz Word", "Cipher form Word"),
    "Открыть папку «Код Марса»": ("Відкрити теку «Код Марса»", "Otwórz folder „Код Марса”", "Open the “Код Марса” folder"),
    "Поделиться: показывать в меню": ("Поділитися: показувати в меню", "Udostępnij: pokazuj w menu", "Share: show in menu"),
    "Поле пустое, копировать нечего": ("Поле порожнє, копіювати нічого", "Pole jest puste, nie ma czego kopiować",
                                       "The field is empty, nothing to copy"),
    "Шифровка скопирована": ("Шифровку скопійовано", "Szyfrogram skopiowany", "Cipher text copied"),
    "Морзянка скопирована": ("Морзянку скопійовано", "Kod Morse’a skopiowany", "Morse code copied"),
    "HEX-ключ скопирован": ("HEX-ключ скопійовано", "Klucz HEX skopiowany", "HEX key copied"),
    "Скопировано": ("Скопійовано", "Skopiowano", "Copied"),
    "Раньше операций нет": ("Раніше операцій немає", "Nie ma wcześniejszych operacji", "No earlier operations"),
    "Это последняя операция": ("Це остання операція", "To ostatnia operacja", "This is the latest operation"),
    "Введите ключ-фразу или вернитесь к списку ключей":
        ("Введіть ключ-фразу або поверніться до списку ключів", "Wpisz frazę-klucz albo wróć do listy kluczy",
         "Enter the key phrase or go back to the key list"),
    "Наступил новый день: выбран ключ «{key}»": ("Настав новий день: обрано ключ «{key}»",
                                                 "Nowy dzień: wybrano klucz „{key}”", "A new day: key “{key}” selected"),
    "Сначала напишите сообщение": ("Спочатку напишіть повідомлення", "Najpierw napisz wiadomość", "Write a message first"),
    "Ошибка при шифровании: {e}": ("Помилка під час шифрування: {e}", "Błąd szyfrowania: {e}", "Encryption error: {e}"),
    "Зашифровано ключом «{key}». В шифровке {n} знаков.":
        ("Зашифровано ключем «{key}». У шифровці {n} знаків.", "Zaszyfrowano kluczem „{key}”. Szyfrogram ma {n} znaków.",
         "Encrypted with key “{key}”. The cipher text has {n} characters."),
    "Вставьте шифровку в поле Base32 или откройте QR-код":
        ("Вставте шифровку в поле Base32 або відкрийте QR-код", "Wklej szyfrogram w pole Base32 albo otwórz kod QR",
         "Paste the cipher text into the Base32 field or open a QR code"),
    "В морзянке есть сигналы, которых не бывает в шифровке.":
        ("У морзянці є сигнали, яких не буває в шифровці.", "Kod Morse’a zawiera sygnały, których nie ma w szyfrogramie.",
         "The Morse code contains signals that never occur in cipher text."),
    "Расшифровано ключом «{key}».": ("Розшифровано ключем «{key}».", "Odszyfrowano kluczem „{key}”.",
                                     "Decrypted with key “{key}”."),
    "Расшифровано ключом «{key}»": ("Розшифровано ключем «{key}»", "Odszyfrowano kluczem „{key}”",
                                    "Decrypted with key “{key}”"),
    "Успешно расшифровано": ("Успішно розшифровано", "Odszyfrowano pomyślnie", "Decrypted successfully"),
    "Поле «Азбука Морзе» пустое": ("Поле «Абетка Морзе» порожнє", "Pole „Alfabet Morse’a” jest puste",
                                   "The Morse code field is empty"),
    "Морзянка переведена в текст: {lang}.": ("Морзянку перекладено в текст: {lang}.",
                                             "Kod Morse’a przetłumaczono na tekst: {lang}.",
                                             "Morse code translated to text: {lang}."),
    " Неизвестные сигналы: {codes}": (" Невідомі сигнали: {codes}", " Nieznane sygnały: {codes}", " Unknown signals: {codes}"),
    "Морзянка переведена в текст": ("Морзянку перекладено в текст", "Kod Morse’a przetłumaczono na tekst",
                                    "Morse code translated to text"),
    "Этот текст нельзя передать азбукой Морзе": ("Цей текст не можна передати абеткою Морзе",
                                                 "Tego tekstu nie da się nadać alfabetem Morse’a",
                                                 "This text cannot be sent in Morse code"),
    "Текст переведён в морзянку: {lang}.": ("Текст перекладено в морзянку: {lang}.",
                                            "Tekst przetłumaczono na kod Morse’a: {lang}.",
                                            "Text translated to Morse code: {lang}."),
    "Нечего передавать: зашифруйте сообщение или вставьте морзянку":
        ("Нічого передавати: зашифруйте повідомлення або вставте морзянку",
         "Nie ma czego nadawać: zaszyfruj wiadomość albo wklej kod Morse’a",
         "Nothing to send: encrypt a message or paste Morse code"),
    "В поле нет сигналов Морзе": ("У полі немає сигналів Морзе", "W polu nie ma sygnałów Morse’a",
                                  "There are no Morse signals in the field"),
    "Не удалось подготовить звук: {e}": ("Не вдалося підготувати звук: {e}", "Nie udało się przygotować dźwięku: {e}",
                                         "Could not prepare the sound: {e}"),
    "Звук в этой системе недоступен: передача показана без звука":
        ("Звук у цій системі недоступний: передачу показано без звуку",
         "Dźwięk w tym systemie jest niedostępny: nadawanie pokazano bez dźwięku",
         "Sound is not available on this system: the transmission is shown silently"),
    "Звук Морзе сохранён ({sec} с) в «Документы\\Код Марса»":
        ("Звук Морзе збережено ({sec} с) у «Документи\\Код Марса»", "Dźwięk Morse’a zapisano ({sec} s) w „Dokumenty\\Код Марса”",
         "Morse sound saved ({sec} s) to “Documents\\Код Марса”"),
    "Не удалось сохранить звук: {e}": ("Не вдалося зберегти звук: {e}", "Nie udało się zapisać dźwięku: {e}",
                                       "Could not save the sound: {e}"),
    "В буфере обмена нет шифровки": ("У буфері обміну немає шифровки", "W schowku nie ma szyfrogramu",
                                     "There is no cipher text on the clipboard"),
    "В буфере обмена нет картинки. Скопируйте QR-код и повторите":
        ("У буфері обміну немає картинки. Скопіюйте QR-код і повторіть", "W schowku nie ma obrazu. Skopiuj kod QR i spróbuj ponownie",
         "There is no picture on the clipboard. Copy the QR code and try again"),
    "Открыть картинку с QR-кодом": ("Відкрити картинку з QR-кодом", "Otwórz obraz z kodem QR", "Open a picture with a QR code"),
    "Изображения": ("Зображення", "Obrazy", "Images"),
    "Текст шифровки": ("Текст шифровки", "Tekst szyfrogramu", "Cipher text"),
    "Все файлы": ("Усі файли", "Wszystkie pliki", "All files"),
    "Не удалось открыть файл: {e}": ("Не вдалося відкрити файл: {e}", "Nie udało się otworzyć pliku: {e}",
                                     "Could not open the file: {e}"),
    "Этот файл не открывается как картинка": ("Цей файл не відкривається як картинка",
                                              "Tego pliku nie można otworzyć jako obrazu", "This file cannot be opened as a picture"),
    "Не удалось прочитать QR-код: {e}": ("Не вдалося прочитати QR-код: {e}", "Nie udało się odczytać kodu QR: {e}",
                                         "Could not read the QR code: {e}"),
    "QR-код на картинке не найден": ("QR-код на картинці не знайдено", "Na obrazie nie znaleziono kodu QR",
                                     "No QR code found in the picture"),
    "QR-код найден, но в нём не шифровка «Кода Марса»":
        ("QR-код знайдено, але в ньому не шифровка «Коду Марса»", "Znaleziono kod QR, ale nie zawiera szyfrogramu „Kodu Marsa”",
         "A QR code was found, but it does not contain a Mars Code cipher"),
    "Не удалось сделать снимок экрана": ("Не вдалося зробити знімок екрана", "Nie udało się zrobić zrzutu ekranu",
                                         "Could not take a screenshot"),
    "На экране не найден QR-код. Откройте его крупнее и повторите":
        ("На екрані не знайдено QR-код. Відкрийте його більшим і повторіть",
         "Na ekranie nie znaleziono kodu QR. Powiększ go i spróbuj ponownie",
         "No QR code found on the screen. Enlarge it and try again"),
    "QR-кода пока нет: сначала зашифруйте сообщение": ("QR-коду поки немає: спочатку зашифруйте повідомлення",
                                                       "Nie ma jeszcze kodu QR: najpierw zaszyfruj wiadomość",
                                                       "There is no QR code yet: encrypt a message first"),
    "Не удалось создать папку «Код Марса» в Документах: {e}":
        ("Не вдалося створити теку «Код Марса» в Документах: {e}", "Nie udało się utworzyć folderu „Код Марса” w Dokumentach: {e}",
         "Could not create the “Код Марса” folder in Documents: {e}"),
    "Не удалось сохранить: {e}": ("Не вдалося зберегти: {e}", "Nie udało się zapisać: {e}", "Could not save: {e}"),
    "QR-код сохранён в «Документы\\Код Марса»": ("QR-код збережено в «Документи\\Код Марса»",
                                                 "Kod QR zapisano w „Dokumenty\\Код Марса”",
                                                 "QR code saved to “Documents\\Код Марса”"),
    "Копирование картинки работает в Windows. Используйте «Сохранить QR»":
        ("Копіювання картинки працює у Windows. Скористайтеся «Зберегти QR»", "Kopiowanie obrazu działa w Windows. Użyj „Zapisz QR”",
         "Copying pictures works on Windows. Use “Save QR”"),
    "Не удалось скопировать картинку: {e}": ("Не вдалося скопіювати картинку: {e}", "Nie udało się skopiować obrazu: {e}",
                                             "Could not copy the picture: {e}"),
    "QR-код скопирован. Вставьте его в мессенджер: Ctrl+V": ("QR-код скопійовано. Вставте його в месенджер: Ctrl+V",
                                                             "Kod QR skopiowany. Wklej go do komunikatora: Ctrl+V",
                                                             "QR code copied. Paste it into a messenger: Ctrl+V"),
    "Сначала зашифруйте сообщение: бланк заполняется шифровкой":
        ("Спочатку зашифруйте повідомлення: бланк заповнюється шифровкою",
         "Najpierw zaszyfruj wiadomość: formularz wypełnia się szyfrogramem",
         "Encrypt a message first: the form is filled with the cipher text"),
    "Бланк {number} сохранён: {n} {sheets} PNG в «Документы\\Код Марса»":
        ("Бланк {number} збережено: {n} {sheets} PNG у «Документи\\Код Марса»",
         "Formularz {number} zapisany: {n} {sheets} PNG w „Dokumenty\\Код Марса”",
         "Form {number} saved: {n} PNG {sheets} in “Documents\\Код Марса”"),
    "Бланк {number} для Word сохранён ({n} {sheets}) в «Документы\\Код Марса»":
        ("Бланк {number} для Word збережено ({n} {sheets}) у «Документи\\Код Марса»",
         "Formularz {number} dla Worda zapisany ({n} {sheets}) w „Dokumenty\\Код Марса”",
         "Word form {number} saved ({n} {sheets}) in “Documents\\Код Марса”"),
    "Не удалось сохранить бланк: {e}": ("Не вдалося зберегти бланк: {e}", "Nie udało się zapisać formularza: {e}",
                                        "Could not save the form: {e}"),
    "Все поля очищены": ("Усі поля очищено", "Wszystkie pola wyczyszczone", "All fields cleared"),
    "\nНажмите здесь, чтобы открыть папку.": ("\nНатисніть тут, щоб відкрити теку.", "\nKliknij tutaj, aby otworzyć folder.",
                                              "\nClick here to open the folder."),
    "Скопировано. В {app} выберите чат и нажмите Ctrl+V": ("Скопійовано. У {app} оберіть чат і натисніть Ctrl+V",
                                                           "Skopiowano. W {app} wybierz czat i naciśnij Ctrl+V",
                                                           "Copied. In {app}, choose a chat and press Ctrl+V"),
    "В {app} выберите чат: текст уже подготовлен": ("У {app} оберіть чат: текст уже підготовлено",
                                                    "W {app} wybierz czat: tekst jest już przygotowany",
                                                    "Choose a chat in {app}: the text is already prepared"),
    "{app} не найден на этом компьютере. Содержимое скопировано: откройте {app} и нажмите Ctrl+V":
        ("{app} не знайдено на цьому комп’ютері. Вміст скопійовано: відкрийте {app} і натисніть Ctrl+V",
         "Nie znaleziono {app} na tym komputerze. Zawartość skopiowano: otwórz {app} i naciśnij Ctrl+V",
         "{app} was not found on this computer. The content is copied: open {app} and press Ctrl+V"),
    "Нечем поделиться: поле пустое": ("Нічим поділитися: поле порожнє", "Nie ma czym się podzielić: pole jest puste",
                                      "Nothing to share: the field is empty"),
    "международная азбука (латиница)": ("міжнародна абетка (латиниця)", "alfabet międzynarodowy (łacinka)",
                                        "international code (Latin)"),
    "русская азбука": ("російська абетка", "alfabet rosyjski", "Russian code"),
    "украинская азбука": ("українська абетка", "alfabet ukraiński", "Ukrainian code"),
    "Автоопределение языка": ("Автовизначення мови", "Automatyczne wykrywanie języka", "Automatic language detection"),
    "Международная (латиница)": ("Міжнародна (латиниця)", "Międzynarodowy (łacinka)", "International (Latin)"),
    "Русская (кириллица)": ("Російська (кирилиця)", "Rosyjski (cyrylica)", "Russian (Cyrillic)"),
    "Украинская (кириллица)": ("Українська (кирилиця)", "Ukraiński (cyrylica)", "Ukrainian (Cyrillic)"),
    "Косая черта (/) между буквами и две косые черты (//) между словами":
        ("Скісна риска (/) між літерами і дві скісні риски (//) між словами",
         "Ukośnik (/) między literami i dwa ukośniki (//) między słowami",
         "Slash (/) between letters and double slash (//) between words"),
    "Пробел между буквами и два пробела между словами": ("Пробіл між літерами і два пробіли між словами",
                                                         "Spacja między literami i dwie spacje między słowami",
                                                         "Space between letters and two spaces between words"),
    "Пробел между буквами и косая черта (/) между словами": ("Пробіл між літерами і скісна риска (/) між словами",
                                                             "Spacja między literami i ukośnik (/) między słowami",
                                                             "Space between letters and slash (/) between words"),
    "Скорость": ("Швидкість", "Prędkość", "Speed"),
    "Скорость, слов в минуту": ("Швидкість, слів за хвилину", "Prędkość, słów na minutę", "Speed, words per minute"),
    "Скорость {wpm} слов в минуту (стандартное слово PARIS): длина точки {ms} мс.":
        ("Швидкість {wpm} слів за хвилину (стандартне слово PARIS): тривалість крапки {ms} мс.",
         "Prędkość {wpm} słów na minutę (słowo wzorcowe PARIS): długość kropki {ms} ms.",
         "Speed {wpm} words per minute (standard word PARIS): dot length {ms} ms."),
    "Паузы между буквами и словами медленнее (скорость Фарнсворта)":
        ("Паузи між літерами і словами повільніші (швидкість Фарнсворта)",
         "Wolniejsze przerwy między literami i słowami (prędkość Farnswortha)",
         "Slower gaps between letters and words (Farnsworth speed)"),
    "Скорость пауз": ("Швидкість пауз", "Prędkość przerw", "Gap speed"),
    "Воспроизведение": ("Відтворення", "Odtwarzanie", "Playback"),
    "Частота тона, Гц": ("Частота тону, Гц", "Częstotliwość tonu, Hz", "Tone frequency, Hz"),
    "Громкость": ("Гучність", "Głośność", "Volume"),
    "Помехи": ("Завади", "Zakłócenia", "Noise"),
    "Разделители в коде Морзе": ("Роздільники в коді Морзе", "Separatory w kodzie Morse’a", "Separators in Morse code"),
    "Азбука и язык передачи": ("Абетка і мова передачі", "Alfabet i język nadawania", "Code table and language"),
    "При автоопределении азбука выбирается сама: по буквам текста при передаче и по самим сигналам при приёме. "
    "Шифровка всегда передаётся латиницей, как на телефоне.":
        ("Під час автовизначення абетка обирається сама: за літерами тексту під час передачі та за самими сигналами "
         "під час прийому. Шифровка завжди передається латиницею, як на телефоні.",
         "Przy automatycznym wykrywaniu alfabet wybiera się sam: według liter tekstu przy nadawaniu i według sygnałów "
         "przy odbiorze. Szyfrogram zawsze nadawany jest łacinką, jak w telefonie.",
         "With automatic detection the code table is chosen by itself: from the letters when sending and from the "
         "signals when receiving. Cipher text is always sent in Latin letters, as on the phone."),
    "Прослушать": ("Прослухати", "Odsłuchaj", "Listen"),
    "Сохранить звук WAV": ("Зберегти звук WAV", "Zapisz dźwięk WAV", "Save sound as WAV"),
    "Сброс": ("Скинути", "Resetuj", "Reset"),
    "Закрыть": ("Закрити", "Zamknij", "Close"),
    "Ключ: {key}_form": ("Ключ: {key}", "Klucz: {key}", "Key: {key}"),
    "Групп на странице: {n}": ("Груп на сторінці: {n}", "Grup na stronie: {n}", "Groups on this page: {n}"),
    "Всего групп: {n}": ("Усього груп: {n}", "Razem grup: {n}", "Total groups: {n}"),
    "QR не\nпомещается": ("QR не\nвміщається", "QR się\nnie mieści", "QR does\nnot fit"),
    "Шифровка": ("Шифровка", "Szyfrogram", "Cipher"),
    "Морзе": ("Морзе", "Morse", "Morse"),
    "(лист {i})": ("(аркуш {i})", "(arkusz {i})", "(sheet {i})"),
    # ошибки ядра
    "Шифровка неполная или повреждена: проверьте, что скопирован весь текст.":
        ("Шифровка неповна або пошкоджена: перевірте, що скопійовано весь текст.",
         "Szyfrogram jest niepełny lub uszkodzony: sprawdź, czy skopiowano cały tekst.",
         "The cipher text is incomplete or damaged: check that all of it was copied."),
    "Ключ не подходит к этой шифровке.": ("Ключ не підходить до цієї шифровки.", "Klucz nie pasuje do tego szyfrogramu.",
                                          "The key does not fit this cipher text."),
    "Не удалось расшифровать: не подошёл ни один ключ. Если сообщение зашифровано ключ-фразой, введите ту же фразу.":
        ("Не вдалося розшифрувати: не підійшов жоден ключ. Якщо повідомлення зашифроване ключ-фразою, введіть ту саму фразу.",
         "Nie udało się odszyfrować: żaden klucz nie pasuje. Jeśli wiadomość zaszyfrowano frazą-kluczem, wpisz tę samą frazę.",
         "Could not decrypt: no key fits. If the message was encrypted with a key phrase, enter the same phrase."),
    "В шифровке недопустимый знак «{ch}». Base32 состоит только из латинских букв A–Z и цифр 2–7.":
        ("У шифровці недопустимий знак «{ch}». Base32 складається лише з латинських літер A–Z і цифр 2–7.",
         "Szyfrogram zawiera niedozwolony znak „{ch}”. Base32 składa się tylko z liter A–Z i cyfr 2–7.",
         "The cipher text contains an invalid character “{ch}”. Base32 uses only letters A–Z and digits 2–7."),
    "Неизвестный знак Морзе: {token}": ("Невідомий знак Морзе: {token}", "Nieznany znak Morse’a: {token}",
                                        "Unknown Morse sign: {token}"),
    "Сообщение слишком длинное для QR-кода. Шифровка и морзянка готовы, их можно отправить текстом.":
        ("Повідомлення задовге для QR-коду. Шифровка й морзянка готові, їх можна надіслати текстом.",
         "Wiadomość jest za długa na kod QR. Szyfrogram i kod Morse’a są gotowe, można je wysłać tekstem.",
         "The message is too long for a QR code. The cipher text and Morse code are ready to send as text."),
}

ERRORS = {
    "incomplete": "Шифровка неполная или повреждена: проверьте, что скопирован весь текст.",
    "wrong_key": "Ключ не подходит к этой шифровке.",
    "no_key": "Не удалось расшифровать: не подошёл ни один ключ. Если сообщение зашифровано ключ-фразой, введите ту же фразу.",
    "bad_char": "В шифровке недопустимый знак «{ch}». Base32 состоит только из латинских букв A–Z и цифр 2–7.",
    "morse_unknown": "Неизвестный знак Морзе: {token}",
    "qr_too_long": "Сообщение слишком длинное для QR-кода. Шифровка и морзянка готовы, их можно отправить текстом.",
}

PLURALS = {("лист", "листа", "листов"): {"uk": ("аркуш", "аркуші", "аркушів"), "pl": ("arkusz", "arkusze", "arkuszy"),
                                         "en": ("sheet", "sheets", "sheets")}}

HELP = [
    ("Как зашифровать", "Напишите текст в поле «Сообщение» и нажмите Enter или «Зашифровать». Появятся шифровка Base32, "
                        "азбука Морзе и QR-код."),
    ("Как отправить", "Нажмите «Копировать» или «Копировать QR» и вставьте в мессенджер (Ctrl+V). Через правую кнопку мыши "
                      "шифровку, морзянку и QR-код можно отправить в Telegram, Viber, Instagram или Delta Chat; список "
                      "мессенджеров настраивается в меню слева от названия."),
    ("Как расшифровать", "Вставьте шифровку в поле «Шифровка Base32»: программа расшифрует её сама. Картинку с QR-кодом "
                         "перетащите в окно или откройте кнопкой «Открыть QR». Принятую морзянку вставьте в поле «Азбука Морзе»."),
    ("Ключи", "Те же 32 ключа, что на телефоне. Каждый день сам выбирается ключ с номером текущего числа; если сообщение "
              "зашифровано ключом другого дня, программа найдёт его сама. Ключ-фраза превращается в ключ через SHA-256."),
    ("Морзе звуком", "Круглый значок звука включает передачу: текущий знак подсвечивается, прозвучавшие сигналы и переданные "
                     "буквы шифровки становятся красными и подчёркнутыми. Поставьте курсор между буквами шифровки или "
                     "между сигналами Морзе, и передача начнётся с этого места."),
    ("SSTV", "Под QR-кодом выберите модель SSTV и нажмите «Передать SSTV»: картинка QR-кода передаётся звуком для радиоканала, "
             "ход передачи виден на картинке. Для длинной шифровки выбирайте PD 120, PD 180, PD 240 или PD 290."),
    ("Бланк шифровки", "Кнопки «Бланк шифровки png» и «doc» сохраняют бланк с номером вида 041026/001, ключом, QR-кодом и "
                       "шифровкой группами по 5 знаков. В Word поля правятся щелчком, а «Выделить всё» берёт только шифровку."),
    ("Файлы и язык", "Всё созданное сохраняется в «Документы\\Код Марса». Язык выбирается кнопкой слева от «Справки». "
                     "Стрелки ← → возвращают операции этого сеанса; язык и настройки программа помнит всегда."),
    ("Совместимость", "Шифровки полностью совместимы с Android-версией «Код Марса» в обе стороны."),
]
HELP_TR = {
    "uk": [("Як зашифрувати", "Напишіть текст у полі «Повідомлення» й натисніть Enter або «Зашифрувати». З’являться шифровка "
                              "Base32, абетка Морзе і QR-код."),
           ("Як надіслати", "Натисніть «Копіювати» або «Копіювати QR» і вставте в месенджер (Ctrl+V). Через праву кнопку миші "
                            "шифровку, морзянку і QR-код можна надіслати в Telegram, Viber, Instagram або Delta Chat; список "
                            "месенджерів налаштовується в меню ліворуч від назви."),
           ("Як розшифрувати", "Вставте шифровку в поле «Шифровка Base32»: програма розшифрує її сама. Картинку з QR-кодом "
                               "перетягніть у вікно або відкрийте кнопкою «Відкрити QR». Прийняту морзянку вставте в поле «Абетка Морзе»."),
           ("Ключі", "Ті самі 32 ключі, що й на телефоні. Щодня сам обирається ключ із номером поточного числа; якщо повідомлення "
                     "зашифроване ключем іншого дня, програма знайде його сама. Ключ-фраза перетворюється на ключ через SHA-256."),
           ("Морзе звуком", "Круглий значок звуку вмикає передачу: поточний знак підсвічується, сигнали, що прозвучали, і передані "
                            "літери шифровки стають червоними й підкресленими. Поставте курсор між літерами шифровки або між "
                            "сигналами Морзе, і передача почнеться з цього місця."),
           ("SSTV", "Під QR-кодом оберіть модель SSTV і натисніть «Передати SSTV»: картинка QR-коду передається звуком для "
                    "радіоканалу, хід передачі видно на картинці. Для довгої шифровки обирайте PD 120, PD 180, PD 240 або PD 290."),
           ("Бланк шифровки", "Кнопки «Бланк шифровки png» і «doc» зберігають бланк із номером на кшталт 041026/001, ключем, "
                              "QR-кодом і шифровкою групами по 5 знаків. У Word поля правляться клацанням, а «Виділити все» бере лише шифровку."),
           ("Файли й мова", "Усе створене зберігається в «Документи\\Код Марса». Мова обирається кнопкою ліворуч від «Довідки». "
                            "Стрілки ← → повертають операції цього сеансу; мову й налаштування програма пам’ятає завжди."),
           ("Сумісність", "Шифровки повністю сумісні з Android-версією «Код Марса» в обидва боки.")],
    "pl": [("Jak zaszyfrować", "Wpisz tekst w polu „Wiadomość” i naciśnij Enter lub „Zaszyfruj”. Pojawią się szyfrogram Base32, "
                               "kod Morse’a i kod QR."),
           ("Jak wysłać", "Naciśnij „Kopiuj” lub „Kopiuj QR” i wklej do komunikatora (Ctrl+V). Prawym przyciskiem myszy szyfrogram, "
                          "kod Morse’a i kod QR można wysłać do Telegrama, Vibera, Instagrama lub Delta Chat; listę komunikatorów "
                          "ustawia się w menu po lewej stronie nazwy."),
           ("Jak odszyfrować", "Wklej szyfrogram w pole „Szyfrogram Base32”: program odszyfruje go sam. Obraz z kodem QR "
                               "przeciągnij do okna lub otwórz przyciskiem „Otwórz QR”. Odebrany kod Morse’a wklej w pole „Alfabet Morse’a”."),
           ("Klucze", "Te same 32 klucze co w telefonie. Każdego dnia wybierany jest klucz o numerze bieżącego dnia; jeśli wiadomość "
                      "zaszyfrowano kluczem innego dnia, program sam go znajdzie. Fraza-klucz zamienia się w klucz przez SHA-256."),
           ("Morse dźwiękiem", "Okrągła ikona dźwięku włącza nadawanie: bieżący znak jest podświetlony, nadane sygnały i litery "
                               "szyfrogramu stają się czerwone i podkreślone. Ustaw kursor między literami szyfrogramu lub między "
                               "sygnałami Morse’a, a nadawanie zacznie się od tego miejsca."),
           ("SSTV", "Pod kodem QR wybierz tryb SSTV i naciśnij „Nadaj SSTV”: obraz kodu QR jest nadawany dźwiękiem dla kanału "
                    "radiowego, postęp widać na obrazie. Dla długiego szyfrogramu wybierz PD 120, PD 180, PD 240 lub PD 290."),
           ("Formularz", "Przyciski „Formularz png” i „doc” zapisują formularz z numerem w rodzaju 041026/001, kluczem, kodem QR i "
                         "szyfrogramem w grupach po 5 znaków. W Wordzie pola edytuje się kliknięciem, a „Zaznacz wszystko” bierze tylko szyfrogram."),
           ("Pliki i język", "Wszystko, co tworzy program, trafia do „Dokumenty\\Код Марса”. Język wybiera się przyciskiem po lewej "
                             "stronie „Pomocy”. Strzałki ← → przywracają operacje tej sesji; język i ustawienia program pamięta zawsze."),
           ("Zgodność", "Szyfrogramy są w pełni zgodne z wersją Android „Kod Marsa” w obie strony.")],
    "en": [("How to encrypt", "Type text in the “Message” field and press Enter or “Encrypt”. The Base32 cipher text, Morse code "
                              "and a QR code appear."),
           ("How to send", "Press “Copy” or “Copy QR” and paste into a messenger (Ctrl+V). With the right mouse button the cipher "
                           "text, Morse code and QR code can be sent to Telegram, Viber, Instagram or Delta Chat; the messenger list "
                           "is set in the menu to the left of the title."),
           ("How to decrypt", "Paste the cipher text into the “Cipher text Base32” field and the program decrypts it. Drag a QR "
                              "picture into the window or open it with “Open QR”. Paste received Morse into the “Morse code” field."),
           ("Keys", "The same 32 keys as on the phone. Each day the key with today's day number is selected; if a message was "
                    "encrypted with another day's key, the program finds it. A key phrase becomes a key through SHA-256."),
           ("Morse by sound", "The round sound icon starts sending: the current sign is highlighted, sent signals and cipher letters "
                              "turn red and underlined. Put the cursor between cipher letters or between Morse signals and sending "
                              "starts from that point."),
           ("SSTV", "Under the QR code choose an SSTV mode and press “Send SSTV”: the QR picture is sent as sound for a radio channel, "
                    "and the progress shows on the picture. For long cipher text choose PD 120, PD 180, PD 240 or PD 290."),
           ("Cipher form", "The “Cipher form png” and “doc” buttons save a form with a number like 041026/001, the key, the QR code "
                           "and the cipher text in groups of 5. In Word the fields are edited by clicking, and “Select all” takes only the cipher text."),
           ("Files and language", "Everything the program creates goes to “Documents\\Код Марса”. The language is chosen with the "
                                  "button left of “Help”. The ← → arrows bring back operations of this session; the language and "
                                  "settings are always remembered."),
           ("Compatibility", "Cipher texts are fully compatible with the Android version of Mars Code in both directions.")],
}


def set_lang(code):
    global _lang
    _lang = code if code in ("ru", "uk", "pl", "en") else "ru"


def lang():
    return _lang


def T(text, **params):
    """Текст на выбранном языке (ключ — русский текст)."""
    if _lang != "ru":
        tr = TR.get(text)
        if tr:
            text = tr[_ORDER[_lang]]
    elif text.endswith("_form"):
        text = text[:-5]
    return text.format(**params) if params else text


def plural(n, forms_ru):
    forms = forms_ru if _lang == "ru" else PLURALS.get(forms_ru, {}).get(_lang, forms_ru)
    if _lang == "en":
        return forms[0] if n == 1 else forms[1]
    if _lang == "pl":
        if n == 1:
            return forms[0]
        return forms[1] if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else forms[2]
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    return forms[1] if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else forms[2]


def help_sections():
    return HELP if _lang == "ru" else HELP_TR[_lang]


def form_labels():
    return {"key": T("Ключ: {key}_form"), "per_page": T("Групп на странице: {n}"), "total": T("Всего групп: {n}"),
            "no_fit": T("QR не\nпомещается")}
