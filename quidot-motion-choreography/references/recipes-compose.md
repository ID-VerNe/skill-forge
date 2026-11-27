# Jetpack Compose Choreography Recipes (Color & Radius Agnostic)

All patterns use standard Kotlin + Jetpack Compose (`androidx.compose.animation.core`, `androidx.compose.foundation`, `androidx.compose.ui`). Always accept `Modifier`, `Color`, and sizing from the caller so the host theme (`apple-ui-principles` or Material/custom tokens) remains in control.

---

## 1. Transient Axis Elongation (过渡轴向拉伸)
Container briefly stretches along the travel axis during a value swap while maintaining volume (`scaleY` slightly compresses) and sliding text inside a clipped mask.

```kotlin
import androidx.compose.animation.*
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.spring
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.graphicsLayer
import kotlinx.coroutines.launch

@Composable
fun ElongatingValueContainer(
    value: Int,
    direction: Int, // +1 forward, -1 backward
    modifier: Modifier = Modifier,
    content: @Composable (Int) -> Unit
) {
    val stretch = remember { Animatable(1f) }
    // The pulse runs on the composition scope, not inside the keyed effect:
    // a key change cancels that effect's coroutine and leaves the Animatable
    // frozen wherever it was — a control stuck mid-stretch.
    val scope = rememberCoroutineScope()

    LaunchedEffect(value) {
        // Self-terminating impulse: the target never leaves 1f, the overshoot
        // comes entirely from initialVelocity. Animatable's MutatorMutex
        // cancels any running animateTo when a new one starts, so nothing is
        // stacked; the guard below only stops repeat taps compounding energy.
        if (stretch.value > 1.0001f) return@LaunchedEffect
        scope.launch {
            stretch.animateTo(1f, spring(dampingRatio = 1f, stiffness = 520f), initialVelocity = 20f)
        }
    }

    Box(
        contentAlignment = Alignment.Center,
        modifier = modifier
            .graphicsLayer {
                scaleX = stretch.value
                scaleY = 1f - (stretch.value - 1f) * 0.25f
            }
            .clipToBounds()
    ) {
        // Nested graphicsLayer inside the scaled box divides the horizontal
        // stretch back out. Without it the AnimatedContent text is stretched
        // by the same 1.28x as the container (see the note below).
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier.graphicsLayer { scaleX = 1f / stretch.value }
        ) {
            AnimatedContent(
                targetState = value,
                transitionSpec = {
                    (slideInHorizontally(spring(0.78f, 420f)) { direction * it } + fadeIn())
                        .togetherWith(
                            slideOutHorizontally(spring(0.78f, 420f)) { -direction * it } + fadeOut()
                        )
                },
                label = "elongating_value"
            ) { target ->
                content(target)
            }
        }
    }
}
```

**The counter-scale layer is mandatory, not decorative.** `scaleX` on an outer `graphicsLayer` scales every descendant, text included; nesting `graphicsLayer { scaleX = 1f / stretch.value }` keeps the glyphs' advance width constant while the container still stretches. Both sides of the `Box` read `stretch.value` inside the draw lambda, so neither causes recomposition.

**Peak width must be budgeted by the caller.** A 1.28x stretch overflows any fixed-width cell, and `.clipToBounds()` on the outer `Box` will clip it. Either reserve the peak width in the parent, or put `clipToBounds` on an inner wrapper that is sized for the peak.

**Reduced motion needs no branch here — but only because the pulse is self-terminating.** `Animatable.animateTo` with a `spring()` reads `MotionDurationScale` from the coroutine context, and that scale is fed from `Settings.Global.animator_duration_scale` (`WindowRecomposer.readAnimationScale`, kept current through a `ContentObserver`). A scale of 0 does not slow the animation down; `SuspendAnimationKt.doAnimationFrameWithScale` sets `playTime = animation.getDurationNanos()` on the first frame, so the animation renders its end value immediately.

That is exactly right for an impulse aimed at the resting value: the end value *is* the state the control is already in, so the whole pulse collapses to nothing. Measured on a MI 9 at scale 0: the `stretch` value logged a single `1.00000` for the lifetime of the tap, while the digit still advanced — the deformation disappeared and the function did not. Measured at scale 1 for comparison: peak 1.31976 decaying over ~250ms.

It is **wrong** for a pulse written as a two-stage target change (`animateTo(1.28f)` then `animateTo(1f)`). At scale 0 that pair renders one frame at 1.28x and the next back at rest — the full-frame flash this skill tells you to avoid, produced by the very collapse you relied on. If you write the pulse that way you must branch; the impulse form removes the need. This is a deliberate difference from the Web side, where `<MotionConfig reducedMotion="user">` does not reach `useMotionValue` + `animate()` at all.

---

## 2. Interruptible Force-Vector Path Deflection (可打断的力矢量路径弯曲)
Uses `Canvas` + `Path.quadraticTo` driven by an `Animatable` spring. Reacts immediately on `awaitFirstDown` and safely handles drag-off cancellations.

```kotlin
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.spring
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import kotlinx.coroutines.launch

@Composable
fun ElasticTrayActionIcon(
    strokeColor: Color,
    bendDirection: Float = 1f, // +1f downward (download), -1f upward (upload)
    onTrigger: () -> Unit,
    modifier: Modifier = Modifier
) {
    val force = remember { Animatable(0f) }
    val scope = rememberCoroutineScope()

    Canvas(
        modifier = modifier.pointerInput(bendDirection) {
            awaitEachGesture {
                awaitFirstDown(requireUnconsumed = false)
                scope.launch {
                    force.animateTo(1f, spring(dampingRatio = 0.55f, stiffness = 520f))
                }
                val up = waitForUpOrCancellation()
                scope.launch {
                    force.animateTo(0f, spring(dampingRatio = 0.42f, stiffness = 320f))
                }
                if (up != null) onTrigger()
            }
        }
    ) {
        val w = size.width
        val h = size.height
        val bendPx = force.value * bendDirection * (h * 0.24f)
        val arrowShiftY = force.value * bendDirection * (h * 0.12f)

        val strokeStyle = Stroke(
            width = w * 0.1f,
            cap = StrokeCap.Round,
            join = StrokeJoin.Round
        )

        // Arrow glyph
        val arrowPath = Path().apply {
            moveTo(w * 0.5f, h * 0.16f + arrowShiftY)
            lineTo(w * 0.5f, h * 0.58f + arrowShiftY)
            moveTo(w * 0.34f, h * 0.44f + arrowShiftY)
            lineTo(w * 0.5f, h * 0.58f + arrowShiftY)
            lineTo(w * 0.66f, h * 0.44f + arrowShiftY)
        }
        drawPath(arrowPath, color = strokeColor, style = strokeStyle)

        // Trampoline baseline using quadraticTo
        val trayPath = Path().apply {
            moveTo(w * 0.2f, h * 0.72f)
            quadraticTo(
                x1 = w * 0.5f,
                y1 = h * 0.72f + bendPx,
                x2 = w * 0.8f,
                y2 = h * 0.72f
            )
        }
        drawPath(trayPath, color = strokeColor, style = strokeStyle)
    }
}
```

---

## 3. Aspect-Ratio & Curvature Morph (长宽比与曲率跨态变形)
Smoothly morphs between a compact circle (`50%` corner) and an expanded rounded shape while siblings yield space via animated `weight` or dimensions.

```kotlin
// Use inside a RowScope
@Composable
fun RowScope.MorphingClusterItem(
    isActive: Boolean,
    activeCornerPercent: Int = 32,
    restingSize: Dp = 36.dp,
    activeHeight: Dp = 48.dp,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit
) {
    val springSpecFloat = remember { spring<Float>(dampingRatio = 0.72f, stiffness = 420f) }
    // 1.6f is a *weight*, not a width ratio. Row distributes its width by
    // weight, so for N equal-weight siblings where one goes 1 -> 1.6:
    //   - active vs. a neighbour: exactly 1.6x (a weight ratio, independent of N)
    //   - active vs. its own resting width: 1.6N/(N + 0.6) — 1.00 at N=1,
    //     1.23 at N=2, 1.33 at N=3, 1.51 at N=10, approaching 1.6 as N grows
    // In a 2- or 3-item cluster the visible growth is therefore ~1.23-1.33x,
    // not the 1.6 the literal suggests. (Idealized: ignores min-width, padding,
    // and any fixed-size siblings, all of which change the split.)
    // There is deliberately no `scale` here: scaling a Row item paints outside
    // its cell and overlaps the neighbours instead of making them yield space.
    val weight by animateFloatAsState(if (isActive) 1.6f else 1f, springSpecFloat, label = "weight")
    val height by animateDpAsState(if (isActive) activeHeight else restingSize, spring(0.72f, 420f), label = "height")
    val cornerPercent by animateIntAsState(if (isActive) activeCornerPercent else 50, spring(0.75f, 420f), label = "corner")

    Box(
        contentAlignment = Alignment.Center,
        modifier = modifier
            .weight(weight)
            .height(height)
            .clip(RoundedCornerShape(percent = cornerPercent))
            .clickable(onClick = onClick)
    ) {
        content()
    }
}
```

---

## 4. Coupled Secondary Follow-Through (主从弹性跟随)
Direct 1:1 pointer drag on the handle (`snapTo`) paired with a 22% dampened vector follow-through on the outer socket read inside `graphicsLayer`.

```kotlin
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.VectorConverter
import androidx.compose.animation.core.spring
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

@Composable
fun SoftSocketJoystick(
    maxTravel: Dp = 20.dp,
    followRatio: Float = 0.22f,
    modifier: Modifier = Modifier,
    socket: @Composable (Modifier) -> Unit,
    knob: @Composable (Modifier) -> Unit
) {
    val offset = remember { Animatable(Offset.Zero, Offset.VectorConverter) }
    val scope = rememberCoroutineScope()
    val maxPx = with(LocalDensity.current) { maxTravel.toPx() }

    val resetSpring = {
        scope.launch {
            offset.animateTo(Offset.Zero, spring(dampingRatio = 0.55f, stiffness = 360f))
        }
    }

    Box(contentAlignment = Alignment.Center, modifier = modifier) {
        // Secondary dampened socket (GPU-only translation via graphicsLayer)
        socket(
            Modifier.graphicsLayer {
                translationX = offset.value.x * followRatio
                translationY = offset.value.y * followRatio
            }
        )

        // Primary 1:1 draggable handle
        knob(
            Modifier
                .graphicsLayer {
                    translationX = offset.value.x
                    translationY = offset.value.y
                }
                .pointerInput(maxPx) {
                    detectDragGestures(
                        onDrag = { change, dragAmount ->
                            change.consume()
                            scope.launch {
                                val candidate = offset.value + dragAmount
                                val dist = candidate.getDistance()
                                val clamped = if (dist > maxPx && dist > 0f) {
                                    candidate * (maxPx / dist)
                                } else candidate
                                offset.snapTo(clamped)
                            }
                        },
                        onDragEnd = { resetSpring() },
                        onDragCancel = { resetSpring() }
                    )
                }
        )
    }
}
```

---

## 5. Synchronous Extrusion Collapse (同步 Z 轴下沉压缩)
Listens to `MutableInteractionSource` press state immediately; draws a solid bottom lip with `drawBehind` and compresses the face downward via `graphicsLayer`.

```kotlin
@Composable
fun TactileExtrudedSurface(
    lipColor: Color,
    cornerRadius: Dp = 16.dp,
    lipHeight: Dp = 5.dp,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit
) {
    val interactionSource = remember { MutableInteractionSource() }
    val isPressed by interactionSource.collectIsPressedAsState()

    val pressOffset by animateDpAsState(
        targetValue = if (isPressed) lipHeight - 1.dp else 0.dp,
        animationSpec = spring(dampingRatio = 0.78f, stiffness = 680f),
        label = "extrusion_press"
    )

    Box(
        contentAlignment = Alignment.Center,
        modifier = modifier
            .padding(bottom = lipHeight)
            .drawBehind {
                val r = CornerRadius(cornerRadius.toPx())
                drawRoundRect(
                    color = lipColor,
                    topLeft = Offset(0f, lipHeight.toPx()),
                    size = size,
                    cornerRadius = r
                )
            }
            .graphicsLayer { translationY = pressOffset.toPx() }
            .clickable(
                interactionSource = interactionSource,
                indication = null,
                onClick = onClick
            )
    ) {
        content()
    }
}
```

---

## 6. Shared-Boundary Bridging (共享边界流体衔接)
Provides a density-aware `FlaredTabShape` with smooth inverted concave skirts (`quadraticTo`) contained cleanly inside the component's bounds, ideal for pairing with animated horizontal tab offsets or `SharedTransitionLayout`.

```kotlin
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Outline
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.LayoutDirection

class FlaredTabShape(
    private val topRadius: Dp,
    private val skirtRadius: Dp
) : Shape {
    override fun createOutline(
        size: Size,
        layoutDirection: LayoutDirection,
        density: Density
    ): Outline = with(density) {
        val w = size.width
        val h = size.height
        val tr = topRadius.toPx().coerceAtMost((w - skirtRadius.toPx() * 2f) / 2f)
        val sr = skirtRadius.toPx().coerceAtMost(h / 2f)

        val path = Path().apply {
            // Left concave skirt (contained safely inside 0..w)
            moveTo(0f, h)
            quadraticTo(sr, h, sr, h - sr)
            lineTo(sr, tr)
            quadraticTo(sr, 0f, sr + tr, 0f)
            // Top edge & right corner
            lineTo(w - sr - tr, 0f)
            quadraticTo(w - sr, 0f, w - sr, tr)
            lineTo(w - sr, h - sr)
            // Right concave skirt
            quadraticTo(w - sr, h, w, h)
            close()
        }
        Outline.Generic(path)
    }
}
```
