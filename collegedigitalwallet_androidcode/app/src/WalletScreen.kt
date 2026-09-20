package com.example.collegedigitalwallet

import android.widget.Toast
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ExitToApp
import androidx.compose.material.icons.filled.Bluetooth
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.example.collegedigitalwallet.api.RetrofitClient
import com.example.collegedigitalwallet.model.TransactionItem
import com.example.collegedigitalwallet.model.TransactionListResponse
import kotlinx.coroutines.delay
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import kotlin.math.abs

private enum class HistoryRange {
    LAST_7_DAYS,
    LAST_30_DAYS
}

private fun parseTransactionDate(raw: String): Date? {
    val candidates = listOf(
        "EEE, dd MMM yyyy HH:mm:ss z",     // Fri, 11 Apr 2026 10:20:30 GMT
        "yyyy-MM-dd'T'HH:mm:ss'Z'",        // 2026-04-11T10:20:30Z
        "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'",    // 2026-04-11T10:20:30.123Z
        "yyyy-MM-dd HH:mm:ss",             // 2026-04-11 10:20:30
        "yyyy-MM-dd'T'HH:mm:ss"            // 2026-04-11T10:20:30
    )

    for (pattern in candidates) {
        try {
            val formatter = SimpleDateFormat(pattern, Locale.ENGLISH)
            formatter.timeZone = TimeZone.getTimeZone("UTC")
            val parsed = formatter.parse(raw)
            if (parsed != null) return parsed
        } catch (_: Exception) {
        }
    }

    return null
}

private fun isInSelectedRange(rawDate: String, range: HistoryRange): Boolean {
    val txDate = parseTransactionDate(rawDate) ?: return true

    val nowMillis = System.currentTimeMillis()
    val txMillis = txDate.time
    val oneDayMillis = 24L * 60L * 60L * 1000L

    // Use absolute difference so slight timezone/server offset does not hide today's transactions
    val diffDays = abs(nowMillis - txMillis) / oneDayMillis

    return when (range) {
        HistoryRange.LAST_7_DAYS -> diffDays <= 7L
        HistoryRange.LAST_30_DAYS -> diffDays <= 30L
    }
}

private fun getStudentPhotoRes(username: String?): Int {
    return when ((username ?: "").trim().lowercase()) {
        "ayudh" -> R.drawable.ayudh
        "subhash" -> R.drawable.subhash
        "chetan" -> R.drawable.chetan
        "ayush" -> R.drawable.aayush
        "pawan" -> R.drawable.pawan
        else -> R.drawable.student_avatar
    }
}

@Composable
fun WalletScreen(
    refreshKey: Int = 0,
    onOfflineTap: () -> Unit = {},
    onOnlineTap: () -> Unit = {},
    onLogout: () -> Unit = {}
) {
    val context = LocalContext.current

    var txList by remember { mutableStateOf<List<TransactionItem>>(emptyList()) }
    var loadingTx by remember { mutableStateOf(false) }

    var selectedFilter by remember { mutableStateOf(HistoryRange.LAST_7_DAYS) }

    var showLogoutDialog by remember { mutableStateOf(false) }

    val filteredTxList = remember(txList, selectedFilter) {
        txList.filter { tx ->
            isInSelectedRange(tx.created_at, selectedFilter)
        }
    }

    val bg = Brush.verticalGradient(
        colors = listOf(
            Color(0xFF0B0F2B),
            Color(0xFF1A237E),
            Color(0xFF283593)
        )
    )

    val screenW = LocalConfiguration.current.screenWidthDp.dp
    val photoW = screenW * 0.26f
    val photoH = photoW * 1.28f

    fun fetchTransactions(showErrorToast: Boolean = false, showLoading: Boolean = false) {
        val u = UserSession.username
        if (u.isNullOrBlank()) return

        if (showLoading) {
            loadingTx = true
        }

        RetrofitClient.api.getTransactions(u).enqueue(object : Callback<TransactionListResponse> {
            override fun onResponse(
                call: Call<TransactionListResponse>,
                response: Response<TransactionListResponse>
            ) {
                loadingTx = false
                val body = response.body()

                if (response.isSuccessful && body?.status == "success") {
                    txList = body.transactions.sortedByDescending {
                        parseTransactionDate(it.created_at)?.time ?: Long.MIN_VALUE
                    }
                } else {
                    if (showErrorToast) {
                        Toast.makeText(context, "Failed to load transactions", Toast.LENGTH_SHORT).show()
                    }
                }
            }

            override fun onFailure(call: Call<TransactionListResponse>, t: Throwable) {
                loadingTx = false
                if (showErrorToast) {
                    Toast.makeText(context, "Backend not reachable", Toast.LENGTH_SHORT).show()
                }
            }
        })
    }

    LaunchedEffect(refreshKey, UserSession.username) {
        fetchTransactions(showErrorToast = true, showLoading = true)

        while (true) {
            delay(2000)
            fetchTransactions(showErrorToast = false, showLoading = false)
        }
    }

    Scaffold(
        containerColor = Color.Transparent,
        bottomBar = {
            NavigationBar(
                containerColor = Color(0xFFEFEFEF),
                tonalElevation = 10.dp
            ) {
                NavigationBarItem(
                    selected = false,
                    onClick = onOnlineTap,
                    icon = { Icon(Icons.Filled.Wifi, contentDescription = "Online Tap") },
                    label = { Text("Online Tap") }
                )

                Text(
                    text = "|",
                    color = Color.Gray,
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(horizontal = 2.dp)
                )

                NavigationBarItem(
                    selected = false,
                    onClick = onOfflineTap,
                    icon = { Icon(Icons.Filled.Bluetooth, contentDescription = "Offline Tap") },
                    label = { Text("Offline Tap") }
                )

                Text(
                    text = "|",
                    color = Color.Gray,
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(horizontal = 2.dp)
                )

                NavigationBarItem(
                    selected = false,
                    onClick = {
                        showLogoutDialog = true
                    },
                    icon = { Icon(Icons.AutoMirrored.Filled.ExitToApp, contentDescription = "Logout") },
                    label = { Text("Logout") }
                )
            }
        }
    ) { innerPadding ->

        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(bg)
                .padding(innerPadding)

        ) {
            if (showLogoutDialog) {
                AlertDialog(
                    onDismissRequest = { showLogoutDialog = false },
                    title = {
                        Text(
                            text = "Confirm Logout",
                            fontWeight = FontWeight.Bold
                        )
                    },
                    text = {
                        Text("Are you sure you want to logout?")
                    },
                    confirmButton = {
                        TextButton(
                            onClick = {
                                showLogoutDialog = false
                                UserSession.clear()
                                Toast.makeText(context, "Logged out successfully ✅", Toast.LENGTH_SHORT).show()
                                onLogout()
                            }
                        ) {
                            Text("Logout")
                        }
                    },
                    dismissButton = {
                        TextButton(
                            onClick = {
                                showLogoutDialog = false
                            }
                        ) {
                            Text("Cancel")
                        }
                    }
                )
            }
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 16.dp),
                contentPadding = PaddingValues(top = 16.dp, bottom = 90.dp)
            ) {

                item {
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        colors = CardDefaults.cardColors(containerColor = Color.White),
                        elevation = CardDefaults.cardElevation(6.dp),
                        shape = MaterialTheme.shapes.medium
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 12.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Image(
                                painter = painterResource(id = R.drawable.lmulogo),
                                contentDescription = "London Metropolitan University",
                                modifier = Modifier.height(36.dp)
                            )
                            Image(
                                painter = painterResource(id = R.drawable.ick_logo),
                                contentDescription = "Islington College",
                                modifier = Modifier.height(36.dp)
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(14.dp))
                }

                item {
                    DemoStyleCard(modifier = Modifier.fillMaxWidth()) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 18.dp, vertical = 16.dp)
                        ) {
                            Spacer(modifier = Modifier.height(10.dp))

                            Box(modifier = Modifier.fillMaxWidth()) {
                                Card(
                                    modifier = Modifier.align(Alignment.Center),
                                    shape = MaterialTheme.shapes.small,
                                    colors = CardDefaults.cardColors(containerColor = Color(0xFFEAEAEA)),
                                    elevation = CardDefaults.cardElevation(6.dp)
                                ) {
                                    Text(
                                        text = "Digital ID Card",
                                        modifier = Modifier.padding(horizontal = 18.dp, vertical = 8.dp),
                                        style = MaterialTheme.typography.labelLarge,
                                        fontWeight = FontWeight.SemiBold,
                                        fontStyle = androidx.compose.ui.text.font.FontStyle.Italic,
                                        color = Color.Black
                                    )
                                }
                            }

                            Spacer(modifier = Modifier.height(16.dp))

                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.Top
                            ) {
                                Column(
                                    modifier = Modifier
                                        .weight(1f)
                                        .padding(end = 12.dp)
                                ) {
                                    Text(
                                        text = UserSession.fullName ?: (UserSession.username ?: "Unknown"),
                                        style = MaterialTheme.typography.titleLarge,
                                        fontWeight = FontWeight.Bold,
                                        color = Color.White,
                                        maxLines = 2
                                    )

                                    Spacer(modifier = Modifier.height(12.dp))

                                    Text(
                                        text = "ID: ${UserSession.studentId ?: "N/A"}",
                                        style = MaterialTheme.typography.bodyMedium,
                                        fontWeight = FontWeight.SemiBold,
                                        color = Color.White.copy(alpha = 0.9f)
                                    )

                                    Spacer(modifier = Modifier.height(14.dp))

                                    Text(
                                        text = UserSession.program ?: "N/A",
                                        style = MaterialTheme.typography.bodyMedium,
                                        fontWeight = FontWeight.SemiBold,
                                        color = Color.White.copy(alpha = 0.65f),
                                        maxLines = 4
                                    )
                                }

                                Card(
                                    shape = MaterialTheme.shapes.large,
                                    colors = CardDefaults.cardColors(containerColor = Color(0xFF9EC3E5)),
                                    border = BorderStroke(1.dp, Color.White.copy(alpha = 0.20f)),
                                    modifier = Modifier
                                        .width(photoW)
                                        .height(photoH)
                                ) {
                                    Image(
                                        painter = painterResource(id = getStudentPhotoRes(UserSession.username)),
                                        contentDescription = "Student Photo",
                                        modifier = Modifier.fillMaxSize(),
                                        contentScale = ContentScale.Crop
                                    )
                                }
                            }

                            Spacer(modifier = Modifier.height(6.dp))
                        }
                    }

                    Spacer(modifier = Modifier.height(18.dp))
                }

                item {
                    DemoStyleCard(modifier = Modifier.fillMaxWidth()) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 18.dp, vertical = 16.dp)
                        ) {
                            Spacer(modifier = Modifier.height(8.dp))

                            Card(
                                shape = MaterialTheme.shapes.small,
                                colors = CardDefaults.cardColors(containerColor = Color(0xFFEAEAEA)),
                                elevation = CardDefaults.cardElevation(6.dp),
                                modifier = Modifier.padding(start = 6.dp)
                            ) {
                                Text(
                                    text = "Token Info",
                                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
                                    style = MaterialTheme.typography.labelLarge,
                                    fontWeight = FontWeight.SemiBold,
                                    fontStyle = androidx.compose.ui.text.font.FontStyle.Italic,
                                    color = Color.Black
                                )
                            }

                            Spacer(modifier = Modifier.height(16.dp))

                            Column(modifier = Modifier.fillMaxWidth(0.78f)) {
                                Text(
                                    text = UserSession.studentId ?: "N/A",
                                    style = MaterialTheme.typography.bodyLarge,
                                    fontWeight = FontWeight.SemiBold,
                                    color = Color.White.copy(alpha = 0.92f)
                                )

                                Spacer(modifier = Modifier.height(14.dp))

                                val bal = UserSession.balance ?: 0.0
                                Row {
                                    Text(
                                        text = "Token Amount: ",
                                        style = MaterialTheme.typography.bodyLarge,
                                        color = Color.White.copy(alpha = 0.9f)
                                    )
                                    Text(
                                        text = String.format(Locale.US, "%.2f", bal),
                                        style = MaterialTheme.typography.bodyLarge,
                                        fontWeight = FontWeight.Bold,
                                        color = Color.White
                                    )
                                }
                            }
                        }
                    }

                    Spacer(modifier = Modifier.height(12.dp))
                }

                item {
                    Card(
                        shape = MaterialTheme.shapes.small,
                        colors = CardDefaults.cardColors(containerColor = Color(0xFFEAEAEA)),
                        elevation = CardDefaults.cardElevation(6.dp),
                        modifier = Modifier.padding(start = 6.dp)
                    ) {
                        Text(
                            text = "Transaction History",
                            modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
                            style = MaterialTheme.typography.labelLarge,
                            fontWeight = FontWeight.SemiBold,
                            fontStyle = androidx.compose.ui.text.font.FontStyle.Italic,
                            color = Color.Black
                        )
                    }

                    Spacer(modifier = Modifier.height(12.dp))
                }

                item {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        FilterPill(
                            text = "Last 7 Days",
                            selected = selectedFilter == HistoryRange.LAST_7_DAYS,
                            onClick = { selectedFilter = HistoryRange.LAST_7_DAYS },
                            modifier = Modifier.weight(1f)
                        )

                        FilterPill(
                            text = "Last 30 Days",
                            selected = selectedFilter == HistoryRange.LAST_30_DAYS,
                            onClick = { selectedFilter = HistoryRange.LAST_30_DAYS },
                            modifier = Modifier.weight(1f)
                        )
                    }

                    Spacer(modifier = Modifier.height(10.dp))
                }

                if (loadingTx) {
                    item {
                        Text(
                            text = "Loading transactions...",
                            color = Color.White.copy(alpha = 0.85f),
                            modifier = Modifier.padding(vertical = 10.dp)
                        )
                    }
                }

                if (!loadingTx && filteredTxList.isEmpty()) {
                    item {
                        Text(
                            text = "No transactions in this period.",
                            color = Color.White.copy(alpha = 0.80f),
                            modifier = Modifier.padding(vertical = 10.dp)
                        )
                    }
                }

                items(filteredTxList) { tx ->
                    TransactionCard(tx)
                    Spacer(modifier = Modifier.height(10.dp))
                }

                item {
                    Text(
                        text = "©2026 Islington College. All Rights Reserved.",
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(bottom = 8.dp),
                        textAlign = TextAlign.Center,
                        color = Color.White.copy(alpha = 0.68f),
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }
        }
    }
}

@Composable
private fun DemoStyleCard(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit
) {
    Card(
        modifier = modifier,
        shape = MaterialTheme.shapes.large,
        colors = CardDefaults.cardColors(containerColor = Color(0xFF0D1450)),
        border = BorderStroke(1.dp, Color.White.copy(alpha = 0.35f)),
        elevation = CardDefaults.cardElevation(8.dp)
    ) { content() }
}

@Composable
private fun FilterPill(
    text: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    val bg = if (selected) Color.White.copy(alpha = 0.22f) else Color.White.copy(alpha = 0.10f)
    val border = if (selected) Color.White.copy(alpha = 0.35f) else Color.White.copy(alpha = 0.22f)

    Surface(
        onClick = onClick,
        modifier = modifier,
        shape = MaterialTheme.shapes.large,
        color = bg,
        border = BorderStroke(1.dp, border),
        tonalElevation = 0.dp,
        shadowElevation = 0.dp
    ) {
        Text(
            text = text,
            modifier = Modifier.padding(horizontal = 18.dp, vertical = 8.dp),
            style = MaterialTheme.typography.labelLarge,
            color = Color.White,
            textAlign = TextAlign.Center
        )
    }
}

@Composable
private fun TransactionCard(tx: TransactionItem) {
    val me = UserSession.username ?: ""

    val isCredit = tx.receiver_username == me
    val amtColor = if (isCredit) Color(0xFF4CAF50) else Color(0xFFF44336)

    val sideText = if (isCredit) {
        "From: ${tx.sender_username}"
    } else {
        "To: ${tx.receiver_username}"
    }

    DemoStyleCard(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = tx.created_at,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = Color.White
                )
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = sideText,
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.White.copy(alpha = 0.85f)
                )
                if (!tx.note.isNullOrBlank()) {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = tx.note,
                        style = MaterialTheme.typography.bodySmall,
                        color = Color.White.copy(alpha = 0.70f)
                    )
                }
            }

            Text(
                text = "Tok ${String.format(Locale.US, "%.2f", tx.amount)}",
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Bold,
                color = amtColor
            )
        }
    }
}