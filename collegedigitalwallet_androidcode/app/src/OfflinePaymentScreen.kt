package com.example.collegedigitalwallet

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothSocket
import android.content.pm.PackageManager
import android.os.Build
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.example.collegedigitalwallet.api.RetrofitClient
import com.example.collegedigitalwallet.model.OfflineTokenItem
import com.example.collegedigitalwallet.model.OfflineTokenPackRequest
import com.example.collegedigitalwallet.model.OfflineTokenPackResponse
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

data class PairedBtDevice(
    val name: String,
    val address: String
)

private const val RFCOMM_CHANNEL = 4

@SuppressLint("DiscouragedPrivateApi", "MissingPermission")
private fun createClassicRfcommSocket(device: BluetoothDevice, channel: Int): BluetoothSocket {
    val method = device.javaClass.getMethod("createRfcommSocket", Int::class.javaPrimitiveType)
    return method.invoke(device, channel) as BluetoothSocket
}

private fun friendlyBtErrorMessage(e: Exception): String {
    val msg = e.message?.lowercase() ?: ""

    return when {
        "read failed" in msg || "socket might closed" in msg || "timeout" in msg ->
            "Merchant is unavailable or not accepting offline payments right now."

        "connection refused" in msg || "service discovery failed" in msg ->
            "Could not reach merchant receiver. Ask the merchant to start offline accepting."

        "host is down" in msg || "unreachable" in msg ->
            "Merchant laptop is not reachable over Bluetooth right now."

        else ->
            "Bluetooth connection failed. Please try again."
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OfflinePaymentScreen(
    username: String,
    onQueued: () -> Unit,
    onBack: () -> Unit = {},
    onPaymentSuccess: () -> Unit = {}
) {
    val context = LocalContext.current
    val bluetoothAdapter: BluetoothAdapter? = BluetoothAdapter.getDefaultAdapter()

    val pairedDevices = remember { mutableStateListOf<PairedBtDevice>() }

    var selectedDeviceAddress by remember { mutableStateOf<String?>(null) }
    var selectedDeviceName by remember { mutableStateOf("") }

    var merchantUsername by remember { mutableStateOf("") }

    var amountText by remember { mutableStateOf("") }
    var noteText by remember { mutableStateOf("") }

    var statusText by remember { mutableStateOf<String?>(null) }
    var successText by remember { mutableStateOf<String?>(null) }

    var helloOk by remember { mutableStateOf(false) }
    var loadingDevices by remember { mutableStateOf(false) }
    var verifyingMerchant by remember { mutableStateOf(false) }
    var paying by remember { mutableStateOf(false) }
    var refreshingTokens by remember { mutableStateOf(false) }

    var deviceDropdownExpanded by remember { mutableStateOf(false) }
    var availableOfflineTokenCount by remember { mutableStateOf(0) }

    val isBusy = loadingDevices || verifyingMerchant || paying

    val bg = Brush.verticalGradient(
        colors = listOf(Color(0xFF0B0F2B), Color(0xFF1A237E), Color(0xFF283593))
    )

    fun refreshOfflineTokenCount() {
        availableOfflineTokenCount = OfflineTokenStore.availableCount(context, username.trim())
    }

    fun requiredPermissions(): Array<String> {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            arrayOf(
                Manifest.permission.BLUETOOTH_SCAN,
                Manifest.permission.BLUETOOTH_CONNECT
            )
        } else {
            arrayOf(
                Manifest.permission.BLUETOOTH,
                Manifest.permission.BLUETOOTH_ADMIN,
                Manifest.permission.ACCESS_FINE_LOCATION
            )
        }
    }

    fun hasRequiredPermissions(): Boolean {
        return requiredPermissions().all { perm ->
            ContextCompat.checkSelfPermission(context, perm) == PackageManager.PERMISSION_GRANTED
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestMultiplePermissions()
    ) { results ->
        val allGranted = results.values.all { it }
        if (allGranted) {
            statusText = null
            successText = null
        } else {
            statusText = "Bluetooth permissions denied. Please allow Bluetooth permissions."
            successText = null
        }
    }

    fun resetMerchantVerification() {
        helloOk = false
        merchantUsername = ""
        successText = null
    }

    fun refreshOfflineTokenPack(silent: Boolean = true) {
        if (username.trim().isBlank()) return

        refreshingTokens = true

        RetrofitClient.api.issueOfflineTokenPack(
            OfflineTokenPackRequest(
                sender_username = username.trim(),
                pack_size = 5
            )
        ).enqueue(object : Callback<OfflineTokenPackResponse> {
            override fun onResponse(
                call: Call<OfflineTokenPackResponse>,
                response: Response<OfflineTokenPackResponse>
            ) {
                refreshingTokens = false
                val body = response.body()

                if (response.isSuccessful && body?.status == "success") {
                    OfflineTokenStore.mergeTokens(context, username.trim(), body.tokens)
                    refreshOfflineTokenCount()

                    if (!silent) {
                        successText = "Offline tokens refreshed ✅"
                        statusText = null
                    }
                } else {
                    refreshOfflineTokenCount()
                    if (!silent) {
                        successText = null
                        statusText = body?.message ?: "Could not refresh offline tokens."
                    }
                }
            }

            override fun onFailure(call: Call<OfflineTokenPackResponse>, t: Throwable) {
                refreshingTokens = false
                refreshOfflineTokenCount()
                if (!silent) {
                    successText = null
                    statusText = "Could not refresh offline tokens. Using saved tokens if available."
                }
            }
        })
    }

    @SuppressLint("MissingPermission")
    fun verifyMerchant(deviceAddress: String, deviceName: String) {
        if (bluetoothAdapter == null) {
            statusText = "Bluetooth not supported on this phone."
            successText = null
            return
        }

        if (!bluetoothAdapter.isEnabled) {
            statusText = "Bluetooth is OFF. Please turn Bluetooth ON first."
            successText = null
            return
        }

        if (!hasRequiredPermissions()) {
            statusText = "Bluetooth permissions are missing."
            successText = null
            return
        }

        verifyingMerchant = true
        helloOk = false
        merchantUsername = ""
        successText = null
        statusText = "Verifying merchant..."

        val targetDevice = bluetoothAdapter.getRemoteDevice(deviceAddress)

        CoroutineScope(Dispatchers.IO).launch {
            var socket: BluetoothSocket? = null

            try {
                bluetoothAdapter.cancelDiscovery()

                socket = createClassicRfcommSocket(targetDevice, RFCOMM_CHANNEL)
                socket.connect()

                val output = socket.outputStream
                val input = socket.inputStream

                val helloJson = JSONObject()
                    .put("type", "hello")
                    .toString()

                output.write(helloJson.toByteArray(Charsets.UTF_8))
                output.flush()

                val buffer = ByteArray(4096)
                val count = input.read(buffer)
                val responseText = if (count > 0) {
                    String(buffer, 0, count, Charsets.UTF_8)
                } else {
                    ""
                }

                val json = if (responseText.isNotBlank()) JSONObject(responseText) else null
                val success = json?.optBoolean("ok", false) == true
                val merchantFromDevice = json?.optString("merchant_username", "")?.trim().orEmpty()

                withContext(Dispatchers.Main) {
                    verifyingMerchant = false
                    helloOk = success

                    if (success) {
                        merchantUsername = merchantFromDevice.ifBlank { deviceName }
                        successText = "Merchant verified ✅"
                        statusText = null
                    } else {
                        merchantUsername = ""
                        successText = null
                        statusText = "Merchant verification failed. Please try again."
                    }
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    verifyingMerchant = false
                    helloOk = false
                    merchantUsername = ""
                    successText = null
                    statusText = friendlyBtErrorMessage(e)
                }
            } finally {
                try {
                    socket?.close()
                } catch (_: Exception) {
                }
            }
        }
    }

    @SuppressLint("MissingPermission")
    fun loadPairedDevices(autoVerify: Boolean = true) {
        successText = null
        statusText = null
        loadingDevices = true
        pairedDevices.clear()
        resetMerchantVerification()

        if (bluetoothAdapter == null) {
            loadingDevices = false
            statusText = "This phone does not support Bluetooth."
            return
        }

        if (!bluetoothAdapter.isEnabled) {
            loadingDevices = false
            statusText = "Bluetooth is OFF. Please turn Bluetooth ON first."
            return
        }

        if (!hasRequiredPermissions()) {
            loadingDevices = false
            statusText = "Bluetooth permissions are missing. Grant permissions first."
            return
        }

        val bonded: Set<BluetoothDevice> = bluetoothAdapter.bondedDevices ?: emptySet()

        if (bonded.isEmpty()) {
            loadingDevices = false
            selectedDeviceAddress = null
            selectedDeviceName = ""
            statusText = "No paired Bluetooth devices found. Pair the merchant laptop first."
            return
        }

        bonded.forEach { device ->
            pairedDevices.add(
                PairedBtDevice(
                    name = device.name ?: "Unknown Device",
                    address = device.address ?: "No Address"
                )
            )
        }

        loadingDevices = false

        when (pairedDevices.size) {
            0 -> {
                selectedDeviceAddress = null
                selectedDeviceName = ""
                statusText = "No paired Bluetooth devices found."
            }

            1 -> {
                val only = pairedDevices.first()
                selectedDeviceAddress = only.address
                selectedDeviceName = only.name
                statusText = "1 paired device found."
                if (autoVerify) {
                    verifyMerchant(only.address, only.name)
                }
            }

            else -> {
                val selectedStillExists =
                    selectedDeviceAddress != null && pairedDevices.any { it.address == selectedDeviceAddress }

                val chosen = if (selectedStillExists) {
                    pairedDevices.first { it.address == selectedDeviceAddress }
                } else {
                    pairedDevices.first()
                }

                selectedDeviceAddress = chosen.address
                selectedDeviceName = chosen.name
                statusText = "${pairedDevices.size} paired devices found."

                if (autoVerify) {
                    verifyMerchant(chosen.address, chosen.name)
                }
            }
        }
    }

    fun sendOfflinePayment() {
        val deviceAddress = selectedDeviceAddress

        if (deviceAddress.isNullOrBlank()) {
            statusText = "No merchant device available."
            successText = null
            return
        }

        if (!helloOk || merchantUsername.isBlank()) {
            statusText = "Merchant is not verified yet."
            successText = null
            return
        }

        val amt = amountText.toDoubleOrNull()
        if (amt == null || amt <= 0.0) {
            Toast.makeText(context, "Enter a valid amount", Toast.LENGTH_SHORT).show()
            return
        }

        val currentBalance = UserSession.balance ?: 0.0
        if (amt > currentBalance) {
            Toast.makeText(context, "Insufficient balance", Toast.LENGTH_SHORT).show()
            return
        }

        val nextToken: OfflineTokenItem? = OfflineTokenStore.peekNextToken(context, username.trim())
        if (nextToken == null) {
            successText = null
            statusText = "No offline tokens available. Go online once and tap Refresh Tokens."
            return
        }

        if (amt > nextToken.max_amount) {
            successText = null
            statusText = "Amount is higher than this offline token limit. Refresh tokens while online."
            return
        }

        if (bluetoothAdapter == null) {
            statusText = "Bluetooth not supported on this phone."
            successText = null
            return
        }

        if (!bluetoothAdapter.isEnabled) {
            statusText = "Bluetooth is OFF. Please turn Bluetooth ON first."
            successText = null
            return
        }

        if (!hasRequiredPermissions()) {
            statusText = "Bluetooth permissions are missing."
            successText = null
            return
        }

        paying = true
        successText = null
        statusText = "Processing payment..."

        val targetDevice = bluetoothAdapter.getRemoteDevice(deviceAddress)

        CoroutineScope(Dispatchers.IO).launch {
            var socket: BluetoothSocket? = null

            try {
                bluetoothAdapter.cancelDiscovery()

                socket = createClassicRfcommSocket(targetDevice, RFCOMM_CHANNEL)
                socket.connect()

                val output = socket.outputStream
                val input = socket.inputStream

                val clientTxId = "BT-${System.currentTimeMillis()}"

                val payJson = JSONObject()
                    .put("type", "pay")
                    .put("merchant_username", merchantUsername.trim())
                    .put("sender_username", username.trim())
                    .put("amount", amt)
                    .put("note", noteText.trim())
                    .put("client_tx_id", clientTxId)
                    .put("offline_token_id", nextToken.token_id)
                    .put("offline_token_nonce", nextToken.nonce)
                    .put("offline_token_expires_at", nextToken.expires_at)
                    .put("offline_token_signature", nextToken.signature)
                    .toString()

                output.write(payJson.toByteArray(Charsets.UTF_8))
                output.flush()

                val buffer = ByteArray(4096)
                val count = input.read(buffer)
                val responseText = if (count > 0) {
                    String(buffer, 0, count, Charsets.UTF_8)
                } else {
                    ""
                }

                val success = responseText.contains("\"ok\": true") || responseText.contains("\"ok\":true")

                withContext(Dispatchers.Main) {
                    paying = false

                    if (success) {
                        OfflineTokenStore.consumeToken(context, username.trim(), nextToken.token_id)
                        refreshOfflineTokenCount()

                        amountText = ""
                        noteText = ""
                        statusText = null
                        successText = null

                        Toast.makeText(context, "Payment successful ✅", Toast.LENGTH_SHORT).show()
                        onQueued()

                    } else {
                        successText = null
                        statusText = "Offline payment failed. Please try again."
                    }
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    paying = false
                    helloOk = false
                    merchantUsername = ""
                    successText = null
                    statusText = friendlyBtErrorMessage(e)
                }
            } finally {
                try {
                    socket?.close()
                } catch (_: Exception) {
                }
            }
        }
    }

    LaunchedEffect(Unit) {
        refreshOfflineTokenCount()

        if (hasRequiredPermissions()) {
            loadPairedDevices(autoVerify = true)
        } else {
            statusText = "Bluetooth permissions are required for offline payment."
        }

        refreshOfflineTokenPack(silent = true)
    }

    val pairedCount = pairedDevices.size
    val canPay =
        !isBusy &&
                helloOk &&
                selectedDeviceAddress != null &&
                merchantUsername.isNotBlank()

    val showDeviceDropdown = pairedDevices.size >= 2
    val merchantDisplay = merchantUsername.ifBlank {
        if (verifyingMerchant) "Verifying merchant..."
        else if (selectedDeviceName.isNotBlank()) selectedDeviceName
        else "No merchant available"
    }

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
                    text = "Offline Payment",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold
                )

                Spacer(modifier = Modifier.height(10.dp))

                Text(
                    text = "Transport: Bluetooth Classic",
                    color = Color.DarkGray,
                    style = MaterialTheme.typography.bodySmall
                )

                Spacer(modifier = Modifier.height(6.dp))

                Text(
                    text = "Offline tokens available: $availableOfflineTokenCount",
                    color = Color.DarkGray,
                    style = MaterialTheme.typography.bodySmall
                )

                Spacer(modifier = Modifier.height(12.dp))

                if (loadingDevices) {
                    Text("Checking paired Bluetooth devices...", color = Color.DarkGray)
                    Spacer(modifier = Modifier.height(8.dp))
                }

                if (refreshingTokens) {
                    Text("Refreshing offline token pack...", color = Color.DarkGray)
                    Spacer(modifier = Modifier.height(8.dp))
                }

                statusText?.let {
                    Text(it, color = Color(0xFFB00020))
                    Spacer(modifier = Modifier.height(8.dp))
                }

                successText?.let {
                    Text(it, color = Color(0xFF1B5E20))
                    Spacer(modifier = Modifier.height(8.dp))
                }

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End
                ) {
                    TextButton(
                        onClick = {
                            if (!hasRequiredPermissions()) {
                                permissionLauncher.launch(requiredPermissions())
                            } else {
                                loadPairedDevices(autoVerify = true)
                            }
                            refreshOfflineTokenPack(silent = false)
                        },
                        enabled = !isBusy
                    ) {
                        Text("Retry")
                    }
                }

                Spacer(modifier = Modifier.height(6.dp))

                Text(
                    text = "Paired devices: $pairedCount",
                    color = Color.DarkGray,
                    style = MaterialTheme.typography.bodySmall
                )

                Spacer(modifier = Modifier.height(8.dp))

                if (!showDeviceDropdown) {
                    Text(text = "Merchant", fontWeight = FontWeight.SemiBold)
                    Spacer(modifier = Modifier.height(6.dp))

                    OutlinedTextField(
                        value = merchantDisplay,
                        onValueChange = {},
                        readOnly = true,
                        enabled = false,
                        modifier = Modifier.fillMaxWidth()
                    )
                } else {
                    Text(text = "Select Merchant", fontWeight = FontWeight.SemiBold)
                    Spacer(modifier = Modifier.height(8.dp))

                    ExposedDropdownMenuBox(
                        expanded = deviceDropdownExpanded,
                        onExpandedChange = {
                            if (!isBusy) deviceDropdownExpanded = !deviceDropdownExpanded
                        }
                    ) {
                        OutlinedTextField(
                            value = selectedDeviceName.ifBlank { "Select device" },
                            onValueChange = {},
                            readOnly = true,
                            enabled = pairedDevices.isNotEmpty() && !isBusy,
                            label = { Text("Paired Device") },
                            trailingIcon = {
                                ExposedDropdownMenuDefaults.TrailingIcon(expanded = deviceDropdownExpanded)
                            },
                            modifier = Modifier
                                .menuAnchor()
                                .fillMaxWidth()
                        )

                        ExposedDropdownMenu(
                            expanded = deviceDropdownExpanded,
                            onDismissRequest = { deviceDropdownExpanded = false }
                        ) {
                            pairedDevices.forEach { device ->
                                DropdownMenuItem(
                                    text = { Text(device.name) },
                                    onClick = {
                                        deviceDropdownExpanded = false
                                        selectedDeviceAddress = device.address
                                        selectedDeviceName = device.name
                                        resetMerchantVerification()
                                        verifyMerchant(device.address, device.name)
                                    }
                                )
                            }
                        }
                    }

                    Spacer(modifier = Modifier.height(10.dp))

                    OutlinedTextField(
                        value = merchantDisplay,
                        onValueChange = {},
                        readOnly = true,
                        enabled = false,
                        label = { Text("Merchant") },
                        modifier = Modifier.fillMaxWidth()
                    )
                }

                Spacer(modifier = Modifier.height(12.dp))

                OutlinedTextField(
                    value = amountText,
                    onValueChange = { amountText = it },
                    label = { Text("Amount (Tokens)") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(modifier = Modifier.height(12.dp))

                OutlinedTextField(
                    value = noteText,
                    onValueChange = { noteText = it },
                    label = { Text("Note (optional)") },
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(modifier = Modifier.height(18.dp))

                Button(
                    enabled = canPay,
                    onClick = { sendOfflinePayment() },
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Color(0xFF4F67A9),
                        contentColor = Color.White
                    )
                ) {
                    Text(
                        when {
                            paying -> "Processing..."
                            verifyingMerchant -> "Verifying..."
                            else -> "Pay Offline"
                        }
                    )
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