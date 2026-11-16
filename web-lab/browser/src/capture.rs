//! Window capture for the live preview panel (macOS only).
//!
//! Reaches the engine's real `WKWebView` through tao's `ns_view` subview tree and
//! asks WebKit for a snapshot. Nothing passes through the window server, so no
//! Screen Recording TCC permission is involved. The completion is async on the
//! main runloop: `begin` returns immediately and fills `slot` (pinging `done`)
//! when the image lands, while the control HTTP thread keeps blocking on `done`.

#[cfg(target_os = "macos")]
pub mod active {
    use std::ffi::c_void;
    use std::sync::mpsc::Sender;
    use std::sync::{Arc, Mutex};

    use block2::RcBlock;
    use objc2::rc::Retained;
    use objc2::runtime::{AnyClass, AnyObject};
    use objc2_app_kit::{
        NSBitmapImageFileType, NSBitmapImageRep, NSBitmapImageRepPropertyKey, NSImage, NSView,
    };
    use objc2_foundation::{NSDictionary, NSError};
    use objc2_web_kit::{WKSnapshotConfiguration, WKWebView};

    /// The snapshot outcome, exactly once per capture.
    pub type CaptureSlot = Arc<Mutex<Option<Result<String, String>>>>;

    const JPEG_QUALITY: f64 = 0.7;

    /// Ask WebKit for a JPEG snapshot of the first WKWebView under `ns_view`.
    /// Returns once the request is dispatched; `slot` receives the base64 JPEG
    /// (or the failure) and `done` is pinged when either happens.
    pub unsafe fn begin_webview_jpeg(
        ns_view: *mut c_void,
        slot: CaptureSlot,
        done: Sender<()>,
    ) -> Result<(), String> {
        let Some(view) = Retained::retain(ns_view as *mut NSView) else {
            return Err("the window's view is gone".to_string());
        };
        let Some(webview) = find_webview(&view) else {
            return Err("no embedded web view found under the window".to_string());
        };

        let slot_for_block = Arc::clone(&slot);
        let done_for_block = done.clone();
        let block = RcBlock::new(move |image: *mut NSImage, _error: *mut NSError| {
            let outcome = unsafe {
                match Retained::retain(image) {
                    Some(image) => encode_jpeg(&image).map(|bytes| base64_encode(&bytes)),
                    None => Err("the snapshot produced no image".to_string()),
                }
            };
            *slot_for_block.lock().expect("capture slot poisoned") = Some(outcome);
            let _ = done_for_block.send(());
        });
        let webview_ref = unsafe { &*webview };
        webview_ref.takeSnapshotWithConfiguration_completionHandler(
            None::<&WKSnapshotConfiguration>,
            &block,
        );
        Ok(())
    }

    /// Depth-first search of the AppKit view tree for the web view itself
    /// (tao's own view hosts it as a subview).
    unsafe fn find_webview(view: &NSView) -> Option<*mut WKWebView> {
        if let Some(class) = AnyClass::get(c"WKWebView") {
            let matches: bool = unsafe { objc2::msg_send![view, isKindOfClass: class] };
            if matches {
                return Some(view as *const NSView as *mut WKWebView);
            }
        }
        let subviews = view.subviews();
        for subview in subviews.iter() {
            if let Some(found) = unsafe { find_webview(&subview) } {
                return Some(found);
            }
        }
        None
    }

    unsafe fn encode_jpeg(image: &NSImage) -> Result<Vec<u8>, String> {
        let Some(tiff) = image.TIFFRepresentation() else {
            return Err("snapshot TIFF representation failed".to_string());
        };
        let Some(rep) = NSBitmapImageRep::imageRepWithData(&tiff) else {
            return Err("snapshot bitmap decode failed".to_string());
        };
        let quality = objc2_foundation::NSNumber::numberWithDouble(JPEG_QUALITY);
        let quality_object: *const AnyObject = Retained::as_ptr(&quality) as *const AnyObject;
        let properties = NSDictionary::<NSBitmapImageRepPropertyKey, AnyObject>::from_slices(
            &[objc2_app_kit::NSImageCompressionFactor],
            &[&*quality_object],
        );
        let Some(data) =
            rep.representationUsingType_properties(NSBitmapImageFileType::JPEG, &properties)
        else {
            return Err("snapshot JPEG encode failed".to_string());
        };
        Ok(data.to_vec())
    }

    /// Standard base64 (RFC 4648, padded) so the crate needs no new dependency.
    fn base64_encode(bytes: &[u8]) -> String {
        const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        let mut encoded = String::with_capacity(bytes.len().div_ceil(3) * 4);
        for chunk in bytes.chunks(3) {
            let bytes = [chunk[0], *chunk.get(1).unwrap_or(&0), *chunk.get(2).unwrap_or(&0)];
            let word = (u32::from(bytes[0]) << 16) | (u32::from(bytes[1]) << 8) | u32::from(bytes[2]);
            encoded.push(ALPHABET[(word >> 18) as usize & 63] as char);
            encoded.push(ALPHABET[(word >> 12) as usize & 63] as char);
            encoded.push(if chunk.len() > 1 { ALPHABET[(word >> 6) as usize & 63] as char } else { '=' });
            encoded.push(if chunk.len() > 2 { ALPHABET[word as usize & 63] as char } else { '=' });
        }
        encoded
    }

    #[cfg(test)]
    mod tests {
        use super::base64_encode;

        #[test]
        fn base64_matches_known_vectors() {
            assert_eq!(base64_encode(b""), "");
            assert_eq!(base64_encode(b"f"), "Zg==");
            assert_eq!(base64_encode(b"fo"), "Zm8=");
            assert_eq!(base64_encode(b"foo"), "Zm9v");
            assert_eq!(base64_encode(b"foobar"), "Zm9vYmFy");
        }
    }
}

#[cfg(not(target_os = "macos"))]
pub mod active {
    use std::ffi::c_void;
    use std::sync::mpsc::Sender;
    use std::sync::Arc;
    use std::sync::Mutex;

    pub type CaptureSlot = Arc<Mutex<Option<Result<String, String>>>>;

    /// Window capture ships macOS-first; other hosts answer with a clear refusal
    /// instead of pretending.
    pub unsafe fn begin_webview_jpeg(
        _ns_view: *mut c_void,
        slot: CaptureSlot,
        done: Sender<()>,
    ) -> Result<(), String> {
        *slot.lock().expect("capture slot poisoned") =
            Some(Err("window capture is macOS-only right now".to_string()));
        let _ = done.send(());
        Ok(())
    }
}

pub use active::CaptureSlot;
#[cfg(target_os = "macos")]
pub use active::begin_webview_jpeg;
#[cfg(not(target_os = "macos"))]
pub use active::begin_webview_jpeg;
