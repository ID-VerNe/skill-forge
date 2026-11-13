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

@Composable
fun ElongatingValueContainer(
    value: Int,
    direction: Int, // +1 forward, -1 backward
    modifier: Modifier = Modifier,
    content: @Composable (Int) -> Unit
) {
    val stretch = remember { Animatable(1f) }

    LaunchedEffect(value) {
        stretch.animateTo(1.28f, spring(dampingRatio = 0.6f, stiffness = 620f))
        stretch.animateTo(1f, spring(dampingRatio = 0.62f, stiffness = 400f))
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
```

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
