package com.example.collegedigitalwallet

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.example.collegedigitalwallet.api.RetrofitClient
import com.example.collegedigitalwallet.model.MerchantListResponse
import com.example.collegedigitalwallet.model.OnlinePayResponse
import com.example.collegedigitalwallet.model.OnlineTokenConsumeRequest
import com.example.collegedigitalwallet.model.OnlineTokenIssueRequest
import com.example.collegedigitalwallet.model.OnlineTokenIssueResponse
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import java.net.Inet4Address
import java.net.NetworkInterface

private fun getNetworkIdFromLocalIp(): String? {
    return try {
        val interfaces = NetworkInterface.getNetworkInterfaces().toList()
        for (ni in interfaces) {
            if (!ni.isUp || ni.isLoopback) continue
            val addrs = ni.inetAddresses.toList()
            for (addr in addrs) {
                if (addr is Inet4Address && !addr.isLoopbackAddress) {
                    val ip = addr.hostAddress ?: continue
                    val parts = ip.split(".")
                    if (parts.size >= 3) return "${parts[0]}.${parts[1]}.${parts[2]}"
                }
            }
        }
        null
    } catch (_: Exception) {
        null
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OnlinePaymentScreen(
    navController: NavController,
    onPaymentSuccess: () -> Unit,
    onBack: () -> Unit = {}
) {
    val context = LocalContext.current

    var merchants by remember { mutableStateOf(listOf<String>()) }
    var selectedMerchant by remember { mutableStateOf("") }

    var discoveryMessage by remember { mutableStateOf<String?>(null) }
    var discoveryLoading by remember { mutableStateOf(false) }
    var lastNetworkId by remember { mutableStateOf<String?>(null) }

    var amountText by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }
    var paying by remember { mutableStateOf(false) }

    val bg = Brush.verticalGradient(
        colors = listOf(Color(0xFF0B0F2B), Color(0xFF1A237E), Color(0xFF283593))
    )

    fun applySelectionRules(list: List<String>) {
        when (list.size) {
            0 -> selectedMerchant = ""
            1 -> selectedMerchant = list.first()
            else -> {
                if (!list.contains(selectedMerchant)) {
                    selectedMerchant = list.first()
                }
            }
        }
    }

    fun fetchMerchants() {
        val networkId = getNetworkIdFromLocalIp()
        lastNetworkId = networkId

        if (networkId == null) {
            merchants = emptyList()
            selectedMerchant = ""
            discoveryMessage = "Could not detect local network. Connect to Wi-Fi and try again."
            return
        }

        discoveryLoading = true
        discoveryMessage = null

        RetrofitClient.api.getMerchants(networkId).enqueue(object : Callback<MerchantListResponse> {
            override fun onResponse(
                call: Call<MerchantListResponse>,
                response: Response<MerchantListResponse>
            ) {
                discoveryLoading = false
                val body = response.body()

                if (response.isSuccessful && body?.status == "success") {
                    merchants = body.merchants
                    applySelectionRules(merchants)

                    discoveryMessage = if (merchants.isEmpty()) {
                        "No merchants found on the same Wi-Fi (networkId=$networkId)."
                    } else null

                } else {
                    merchants = emptyList()
                    selectedMerchant = ""
                    discoveryMessage = body?.message ?: "Failed to load merchants (HTTP ${response.code()})"
                }
            }

            override fun onFailure(call: Call<MerchantListResponse>, t: Throwable) {
                discoveryLoading = false
                merchants = emptyList()
                selectedMerchant = ""
                discoveryMessage = "Backend not reachable. Check Flask IP + Wi-Fi."
            }
        })
    }

    LaunchedEffect(Unit) {
        fetchMerchants()
    }

    val canPay =
        !paying &&
                !discoveryLoading &&
                merchants.isNotEmpty() &&
                selectedMerchant.isNotBlank()

    val shouldShowMerchantSelector = merchants.size >= 2

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(bg)
            .padding(16.dp),
        contentAlignment = Alignment.Center
    ) {
        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(22.dp),
            colors = CardDefaults.cardColors(containerColor = Color(0xFFF2F2F2)),
            elevation = CardDefaults.cardElevation(10.dp)
        ) {
            Column(modifier = Modifier.padding(18.dp)) {

                Text(
                    text = "Online Payment",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold
                )

                Spacer(modifier = Modifier.height(10.dp))

                Text(
                    text = "NetworkId: ${lastNetworkId ?: "unknown"}",
                    color = Color.DarkGray,
                    style = MaterialTheme.typography.bodySmall
                )

                Spacer(modifier = Modifier.height(12.dp))

                if (discoveryLoading) {
                    Text("Searching merchants on your Wi-Fi...", color = Color.DarkGray)
                    Spacer(modifier = Modifier.height(8.dp))
                }

                discoveryMessage?.let {
                    Text(it, color = Color(0xFFB00020))
                    Spacer(modifier = Modifier.height(8.dp))
                }

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End
                ) {
                    TextButton(
                        onClick = { fetchMerchants() },
                        enabled = !discoveryLoading && !paying
                    ) {
                        Text("Retry")
                    }
                }

                Spacer(modifier = Modifier.height(6.dp))

                val activeCount = merchants.size
                if (!discoveryLoading) {
                    Text(
                        text = "Active merchants: $activeCount",
                        color = Color.DarkGray,
                        style = MaterialTheme.typography.bodySmall
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                }

                if (!shouldShowMerchantSelector) {
                    Text(text = "Merchant", fontWeight = FontWeight.SemiBold)
                    Spacer(modifier = Modifier.height(6.dp))

                    OutlinedTextField(
                        value = if (selectedMerchant.isNotBlank()) selectedMerchant else "No merchant available",
                        onValueChange = {},
                        readOnly = true,
                        enabled = false,
                        modifier = Modifier.fillMaxWidth()
                    )

                    if (merchants.size == 1) {
                        Spacer(modifier = Modifier.height(6.dp))
                        Text(
                            text = "Auto-selected: $selectedMerchant",
                            color = Color.DarkGray,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }

                } else {
                    Text(text = "Select Merchant", fontWeight = FontWeight.SemiBold)
                    Spacer(modifier = Modifier.height(8.dp))

                    var expanded by remember { mutableStateOf(false) }

                    ExposedDropdownMenuBox(
                        expanded = expanded,
                        onExpandedChange = { expanded = !expanded }
                    ) {
                        OutlinedTextField(
                            value = selectedMerchant,
                            onValueChange = {},
                            readOnly = true,
                            enabled = merchants.isNotEmpty(),
                            label = { Text("Merchant") },
                            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
                            modifier = Modifier
                                .menuAnchor()
                                .fillMaxWidth()
                        )

                        ExposedDropdownMenu(
                            expanded = expanded,
                            onDismissRequest = { expanded = false }
                        ) {
                            merchants.forEach { m ->
                                DropdownMenuItem(
                                    text = { Text(m) },
                                    onClick = {
                                        selectedMerchant = m
                                        expanded = false
                                    }
                                )
                            }
                        }
                    }
                }

                Spacer(modifier = Modifier.height(12.dp))

                OutlinedTextField(
                    value = amountText,
                    onValueChange = { amountText = it },
                    label = { Text("Amount (Tokens)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(modifier = Modifier.height(12.dp))

                OutlinedTextField(
                    value = note,
                    onValueChange = { note = it },
                    label = { Text("Note (optional)") },
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(modifier = Modifier.height(18.dp))

                Button(
                    enabled = canPay,
                    onClick = {
                        val amt = amountText.toDoubleOrNull()
                        if (amt == null || amt <= 0) {
                            Toast.makeText(context, "Enter a valid amount", Toast.LENGTH_SHORT).show()
                            return@Button
                        }

                        val currentBalance = UserSession.balance ?: 0.0
                        if (amt > currentBalance) {
                            Toast.makeText(context, "Insufficient balance", Toast.LENGTH_SHORT).show()
                            return@Button
                        }

                        val sender = UserSession.username
                        if (sender.isNullOrBlank()) {
                            Toast.makeText(context, "Session missing. Login again.", Toast.LENGTH_SHORT).show()
                            return@Button
                        }

                        if (selectedMerchant.isBlank()) {
                            Toast.makeText(context, "No active merchant available.", Toast.LENGTH_SHORT).show()
                            return@Button
                        }

                        paying = true

                        val issueReq = OnlineTokenIssueRequest(
                            sender_username = sender,
                            merchant_username = selectedMerchant,
                            amount = amt,
                            note = note.ifBlank { null }
                        )

                        RetrofitClient.api.issueOnlineToken(issueReq)
                            .enqueue(object : Callback<OnlineTokenIssueResponse> {
                                override fun onResponse(
                                    call: Call<OnlineTokenIssueResponse>,
                                    response: Response<OnlineTokenIssueResponse>
                                ) {
                                    val issueBody = response.body()

                                    if (!(response.isSuccessful && issueBody?.status == "success")) {
                                        paying = false
                                        Toast.makeText(
                                            context,
                                            issueBody?.message ?: "Token issue failed",
                                            Toast.LENGTH_SHORT
                                        ).show()
                                        return
                                    }

                                    val tokenId = issueBody.token_id
                                    val nonce = issueBody.nonce
                                    val expiresAt = issueBody.expires_at
                                    val signature = issueBody.signature

                                    if (tokenId.isNullOrBlank() || nonce.isNullOrBlank() || expiresAt.isNullOrBlank() || signature.isNullOrBlank()) {
                                        paying = false
                                        Toast.makeText(context, "Invalid token response", Toast.LENGTH_SHORT).show()
                                        return
                                    }

                                    val consumeReq = OnlineTokenConsumeRequest(
                                        token_id = tokenId,
                                        nonce = nonce,
                                        expires_at = expiresAt,
                                        signature = signature
                                    )

                                    RetrofitClient.api.payOnlineTokenized(consumeReq)
                                        .enqueue(object : Callback<OnlinePayResponse> {
                                            override fun onResponse(
                                                call: Call<OnlinePayResponse>,
                                                response: Response<OnlinePayResponse>
                                            ) {
                                                paying = false
                                                val body = response.body()

                                                if (response.isSuccessful && body?.status == "success") {
                                                    UserSession.balance = body.sender_new_balance
                                                    Toast.makeText(context, "Payment successful ✅", Toast.LENGTH_SHORT).show()
                                                    onPaymentSuccess()
                                                } else {
                                                    Toast.makeText(
                                                        context,
                                                        body?.message ?: "Payment failed",
                                                        Toast.LENGTH_SHORT
                                                    ).show()
                                                }
                                            }

                                            override fun onFailure(call: Call<OnlinePayResponse>, t: Throwable) {
                                                paying = false
                                                Toast.makeText(context, "Backend not reachable", Toast.LENGTH_SHORT).show()
                                            }
                                        })
                                }

                                override fun onFailure(call: Call<OnlineTokenIssueResponse>, t: Throwable) {
                                    paying = false
                                    Toast.makeText(context, "Backend not reachable", Toast.LENGTH_SHORT).show()
                                }
                            })
                    },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(if (paying) "Processing..." else "Pay Now")
                }

                Spacer(modifier = Modifier.height(10.dp))

                TextButton(
                    onClick = { onBack() },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("Cancel")
                }
            }
        }
    }
}