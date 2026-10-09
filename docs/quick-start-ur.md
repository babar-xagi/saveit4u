# SaveIt4U — asaan setup

1. **SaveIt4U Setup EXE kholo aur Install dabao.** Python, Node ya FFmpeg alag se install nahi karna. Koi command run nahi karni.
2. **Open SaveIt4U dabao.** Desktop dashboard par shuru mein “Disconnected — waiting for extension” aa sakta hai.
3. **Chrome extension install karo.** Is private release mein ZIP extract karo. Chrome mein Extensions → Manage extensions → Developer mode → Load unpacked se extracted extension folder select karo. Desktop app ka “Install / locate extension” button included folder bhi khol deta hai. Chrome Web Store publication ke baad yeh step “Add to Chrome” ban jayega.
4. **Dono khud connect honge.** Extension ID copy ya paste nahi karni. Status “Connected” hoga. Agar connection toot jaye, app/extension khud reconnect ki koshish karte hain.
5. **YouTube video ya Short kholo.** Quality popup khud aa jayega. Format aur optional transcript language choose karo. Jis quality par click karoge, download background mein shuru ho jayega.
6. **Files dekho.** Desktop app ya extension dashboard mein Open folder dabao. Sab new videos `Downloads/SaveIt4U` mein original titles ke saath save honge. Same title dobara aaye to `(2)`, `(3)` lag jayega.

Dashboard par download speed, downloaded/total data, remaining time, progress aur system receive rate dikhte hain. `~` ka matlab estimated size hai. System receive mein doosri applications ka traffic bhi shamil hota hai.

Maximum quality ke liye MKV choose karo. Compatible H.264 playback ke liye MP4 choose karo; iski available maximum resolution kam ho sakti hai. Transcript sirf tab export hogi jab us video par captions available hon.

Popup na aaye ya detection fail ho to “SaveIt4U” page button / “Detect again” use karo. Manual fallback: desktop app ya extension dashboard mein YouTube link paste karke Choose quality / Find video dabao.

Browser ya dashboard window band karne se background engine download karta rehta hai. Computer restart ke baad unfinished jobs resume kar sakte ho. Installer update active jobs ka continuation state save karta hai; tumhare khud paused kiye hue jobs automatically start nahi hote.

Installer abhi unsigned private build hai. Chrome Web Store publication aur verified publisher code signing public release ke alag steps hain. Browser/Windows ki security warning ko automatically bypass nahi kiya jata.
